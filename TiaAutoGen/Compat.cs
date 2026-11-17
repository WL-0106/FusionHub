using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using Siemens.Engineering;

namespace TiaAutoGen
{
    /// <summary>
    /// Small reflection layer for the handful of Openness calls whose signatures differ
    /// between TIA Portal versions / assembly layouts (V20 single assembly vs V21 split assemblies),
    /// or which are only available as extension methods on the real Siemens assemblies.
    /// </summary>
    internal static class Compat
    {
        private static List<MethodInfo> _extensionMethods;

        public static object GetProp(object instance, string name)
        {
            if (instance == null) return null;
            var pi = instance.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (pi == null) return null;
            try { return pi.GetValue(instance, null); }
            catch { return null; }
        }

        public static string GetString(object instance, string name)
        {
            var value = GetProp(instance, name);
            return value == null ? null : Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        public static IEnumerable<object> Enumerate(object composition)
        {
            var enumerable = composition as IEnumerable;
            if (enumerable == null) yield break;
            foreach (var item in enumerable) yield return item;
        }

        public static object FindByName(object composition, string name)
        {
            if (composition == null || string.IsNullOrEmpty(name)) return null;
            var find = composition.GetType().GetMethod("Find", new[] { typeof(string) });
            if (find != null)
            {
                try { return find.Invoke(composition, new object[] { name }); }
                catch { }
            }
            foreach (var item in Enumerate(composition))
            {
                if (string.Equals(GetString(item, "Name"), name, StringComparison.OrdinalIgnoreCase)) return item;
            }
            return null;
        }

        /// <summary>Create via a plain Create(string) method or extension (screens, tag tables, connections).</summary>
        public static object CreateNamed(object composition, string name)
        {
            if (composition == null) return null;
            var method = composition.GetType().GetMethod("Create", new[] { typeof(string) });
            if (method != null) return method.Invoke(composition, new object[] { name });

            var ext = FindExtension(composition.GetType(), "Create", new[] { typeof(string) }, false);
            if (ext != null) return ext.Invoke(null, new object[] { composition, name });
            return null;
        }

        /// <summary>
        /// Create a typed child (screen, screen item, HMI connection) trying every known Openness shape:
        /// Create(string), Create&lt;T&gt;(string), IEngineeringComposition.Create(Type, params), extension variants.
        /// </summary>
        public static object CreateTyped(object composition, Type itemType, string name, IDictionary<string, object> extra)
        {
            if (composition == null) return null;
            var errors = new List<string>();

            try
            {
                var plain = CreateNamed(composition, name);
                if (plain != null) return plain;
            }
            catch (Exception ex) { errors.Add(Unwrap(ex)); }

            try
            {
                var generic = InvokeGenericMethod(composition, "Create", new[] { typeof(string) }, new[] { itemType }, new object[] { name });
                if (generic != null) return generic;
            }
            catch (Exception ex) { errors.Add(Unwrap(ex)); }

            try
            {
                var iface = composition as IEngineeringComposition;
                if (iface != null)
                {
                    var created = iface.Create(itemType, ToParams(name, extra));
                    if (created != null) return created;
                }
            }
            catch (Exception ex) { errors.Add(Unwrap(ex)); }

            try
            {
                var ext = FindExtension(composition.GetType(), "Create", new[] { typeof(string) }, true);
                if (ext != null)
                {
                    var genericType = itemType;
                    return ext.MakeGenericMethod(genericType).Invoke(null, new object[] { composition, name });
                }
            }
            catch (Exception ex) { errors.Add(Unwrap(ex)); }

            throw new InvalidOperationException(
                "No usable Create(...) overload for " + composition.GetType().FullName + " / " + itemType.FullName +
                (errors.Count > 0 ? " | " + string.Join(" | ", errors.ToArray()) : string.Empty));
        }

        /// <summary>Sets a strongly typed property when possible, otherwise the Openness attribute.</summary>
        public static bool SetMember(object instance, string name, object value)
        {
            if (instance == null || string.IsNullOrEmpty(name)) return false;
            var type = instance.GetType();
            var pi = type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            var targetType = pi == null ? null : pi.PropertyType;

            if (pi != null && pi.CanWrite)
            {
                try
                {
                    pi.SetValue(instance, ConvertValue(value, targetType), null);
                    return true;
                }
                catch { }
            }

            var engineeringObject = instance as IEngineeringObject;
            if (engineeringObject != null)
            {
                try
                {
                    engineeringObject.SetAttribute(name, ConvertValue(value, targetType));
                    return true;
                }
                catch { }
            }
            return false;
        }

        /// <summary>Invoke an instance method by name and parameter signature.</summary>
        public static object InvokeInstance(object target, string name, Type[] signature, object[] args)
        {
            if (target == null) return null;
            var method = target.GetType().GetMethod(name, signature);
            if (method == null) throw new MissingMethodException(target.GetType().FullName, name);
            return method.Invoke(target, args);
        }

        public static object InvokeGenericMethod(object target, string name, Type[] signature, Type[] typeArgs, object[] args)
        {
            if (target == null) return null;
            var method = target.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m => m.Name == name && m.IsGenericMethodDefinition &&
                                     m.GetGenericArguments().Length == typeArgs.Length &&
                                     Matches(m.GetParameters(), signature));
            if (method == null) return null;
            return method.MakeGenericMethod(typeArgs).Invoke(target, args);
        }

        /// <summary>Invoke a static extension method whose first parameter accepts the target.</summary>
        public static object InvokeExtension(object target, string name, Type[] signature, object[] args)
        {
            var method = FindExtension(target.GetType(), name, signature, false);
            if (method == null) throw new MissingMethodException(name + " (extension)", name);
            return method.Invoke(null, new object[] { target }.Concat(args).ToArray());
        }

        public static object InvokeGenericExtension(object target, string name, Type[] signature, Type[] typeArgs, object[] args)
        {
            var method = FindExtension(target.GetType(), name, signature, true);
            if (method == null) throw new MissingMethodException(name + " (generic extension)", name);
            return method.MakeGenericMethod(typeArgs).Invoke(null, new object[] { target }.Concat(args).ToArray());
        }

        private static MethodInfo FindExtension(Type targetType, string name, Type[] signature, bool generic)
        {
            foreach (var method in ExtensionMethods())
            {
                if (method.Name != name) continue;
                if (method.IsGenericMethodDefinition != generic) continue;
                if (generic && method.GetGenericArguments().Length == 0) continue;
                var parameters = method.GetParameters();
                if (parameters.Length != signature.Length + 1) continue;
                if (!parameters[0].ParameterType.IsAssignableFrom(targetType)) continue;
                var ok = true;
                for (var i = 1; i < parameters.Length; i++)
                {
                    if (parameters[i].ParameterType != signature[i - 1]) { ok = false; break; }
                }
                if (ok) return method;
            }
            return null;
        }

        public static void InvalidateExtensionCache()
        {
            _extensionMethods = null;
        }

        private static List<MethodInfo> ExtensionMethods()
        {
            if (_extensionMethods != null) return _extensionMethods;
            var methods = new List<MethodInfo>();
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var assemblyName = assembly.GetName().Name;
                if (assemblyName == null || !assemblyName.StartsWith("Siemens.Engineering", StringComparison.OrdinalIgnoreCase)) continue;
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
                catch { continue; }

                foreach (var type in types)
                {
                    if (!type.IsAbstract || !type.IsSealed) continue; // static class
                    MethodInfo[] declared;
                    try { declared = type.GetMethods(BindingFlags.Public | BindingFlags.Static); }
                    catch { continue; }
                    methods.AddRange(declared);
                }
            }
            _extensionMethods = methods;
            return methods;
        }

        private static bool Matches(ParameterInfo[] parameters, Type[] signature)
        {
            if (parameters.Length != signature.Length) return false;
            for (var i = 0; i < parameters.Length; i++)
            {
                if (parameters[i].ParameterType != signature[i]) return false;
            }
            return true;
        }

        private static IEnumerable<KeyValuePair<string, object>> ToParams(string name, IDictionary<string, object> extra)
        {
            var parameters = new List<KeyValuePair<string, object>>
            {
                new KeyValuePair<string, object>("Name", name)
            };
            if (extra != null)
            {
                foreach (var pair in extra)
                {
                    if (string.Equals(pair.Key, "Name", StringComparison.OrdinalIgnoreCase)) continue;
                    parameters.Add(pair);
                }
            }
            return parameters;
        }

        private static object ConvertValue(object value, Type targetType)
        {
            if (value == null) return null;
            if (targetType == null || targetType == typeof(object)) return value;
            if (targetType.IsAssignableFrom(value.GetType())) return value;
            if (targetType.IsEnum) return Enum.Parse(targetType, Convert.ToString(value, CultureInfo.InvariantCulture), true);
            if (targetType == typeof(string)) return Convert.ToString(value, CultureInfo.InvariantCulture);
            return Convert.ChangeType(value, targetType, CultureInfo.InvariantCulture);
        }

        private static string Unwrap(Exception ex)
        {
            var actual = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
            return actual.Message;
        }
    }
}
