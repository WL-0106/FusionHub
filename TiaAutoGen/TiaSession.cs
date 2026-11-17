using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Siemens.Engineering;
using Siemens.Engineering.Compiler;
using Siemens.Engineering.HmiUnified;
using Siemens.Engineering.HW;
using Siemens.Engineering.HW.Features;
using Siemens.Engineering.SW;

namespace TiaAutoGen
{
    internal sealed class TiaSession : IDisposable
    {
        public TiaPortal Portal { get; private set; }
        public Project Project { get; private set; }

        public TiaSession(bool withUserInterface)
        {
            PreloadOpennessAssemblies();
            var modeName = withUserInterface ? "WithUserInterface" : "WithoutUserInterface";
            var mode = (TiaPortalMode)Enum.Parse(typeof(TiaPortalMode), modeName, true);
            Portal = (TiaPortal)Activator.CreateInstance(typeof(TiaPortal), new object[] { mode });
        }

        /// <summary>
        /// Openness puts some Create/Connect helpers in extension classes of assemblies that are
        /// not loaded until an object of that domain is touched. Load them up-front so the
        /// reflection based compatibility layer can find those methods.
        /// </summary>
        private static void PreloadOpennessAssemblies()
        {
            try
            {
                var directory = Path.GetDirectoryName(typeof(TiaPortal).Assembly.Location);
                if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory)) return;
                foreach (var file in Directory.GetFiles(directory, "Siemens.Engineering*.dll"))
                {
                    try { System.Reflection.Assembly.LoadFrom(file); }
                    catch { }
                }
            }
            catch { }
            Compat.InvalidateExtensionCache();
        }

        public void OpenOrCreate(ProjectSpec spec)
        {
            if (!string.IsNullOrWhiteSpace(spec.OpenProjectPath))
            {
                Project = Portal.Projects.Open(new FileInfo(spec.OpenProjectPath));
                return;
            }

            Directory.CreateDirectory(spec.ProjectDirectory);
            Project = Portal.Projects.Create(new DirectoryInfo(spec.ProjectDirectory), spec.ProjectName);
        }

        public Device AddDevice(string typeIdentifier, string deviceName, Report report)
        {
            var device = Project.Devices.CreateWithItem(typeIdentifier, deviceName, deviceName);
            report.Ok("device created: " + deviceName + " (" + typeIdentifier + ")");
            return device;
        }

        public static string ResolveTypeIdentifier(TiaPortal portal, DeviceSpec spec, Report report)
        {
            if (!string.IsNullOrWhiteSpace(spec.TypeIdentifier)) return spec.TypeIdentifier;

            var keyword = !string.IsNullOrWhiteSpace(spec.CatalogName) ? spec.CatalogName : spec.TypeName;
            if (string.IsNullOrWhiteSpace(keyword))
                throw new ArgumentException("Device " + spec.DeviceName + " needs CatalogName, TypeName or TypeIdentifier.");

            var entries = portal.HardwareCatalog.Find(keyword);
            var candidates = entries
                .Select(e => new
                {
                    Entry = e,
                    TypeIdentifier = Compat.GetString(e, "TypeIdentifier"),
                    TypeName = Compat.GetString(e, "TypeName"),
                    Version = Compat.GetString(e, "Version"),
                    CatalogPath = Compat.GetString(e, "CatalogPath")
                })
                .Where(c => !string.IsNullOrWhiteSpace(c.TypeIdentifier))
                .ToList();

            if (!string.IsNullOrWhiteSpace(spec.TypeName))
            {
                var exact = candidates.Where(c =>
                    string.Equals(c.TypeName, spec.TypeName, StringComparison.OrdinalIgnoreCase)).ToList();
                if (exact.Count > 0) candidates = exact;
                else
                {
                    var contains = candidates.Where(c => c.TypeName != null &&
                        c.TypeName.IndexOf(spec.TypeName, StringComparison.OrdinalIgnoreCase) >= 0).ToList();
                    if (contains.Count > 0) candidates = contains;
                }
            }

            if (candidates.Count == 0)
            {
                var suggestions = entries.Take(10)
                    .Select(e => Compat.GetString(e, "TypeName") + " | " + Compat.GetString(e, "TypeIdentifier"))
                    .ToArray();
                throw new InvalidOperationException(
                    "No hardware catalog entry matched '" + keyword + "'." +
                    (suggestions.Length > 0 ? " Suggestions: " + string.Join("; ", suggestions) : string.Empty));
            }

            var best = candidates
                .OrderByDescending(c => c.Version, new VersionComparer())
                .ThenBy(c => c.CatalogPath)
                .First();

            report.Info("resolved " + keyword + " -> " + best.TypeName + " " + best.Version + " [" + best.TypeIdentifier + "]");
            return best.TypeIdentifier;
        }

        public static IEnumerable<DeviceItem> AllItems(Device device)
        {
            foreach (var item in device.DeviceItems)
            {
                yield return item;
                foreach (var child in AllItems(item)) yield return child;
            }
        }

        private static IEnumerable<DeviceItem> AllItems(DeviceItem item)
        {
            foreach (var child in item.DeviceItems)
            {
                yield return child;
                foreach (var grandChild in AllItems(child)) yield return grandChild;
            }
        }

        public static DeviceItem FindPlcItem(Device device)
        {
            return AllItems(device).FirstOrDefault(item =>
            {
                var container = item.GetService<SoftwareContainer>();
                return container != null && container.Software is PlcSoftware;
            });
        }

        public static DeviceItem FindHmiItem(Device device)
        {
            return AllItems(device).FirstOrDefault(item =>
            {
                var container = item.GetService<SoftwareContainer>();
                return container != null && container.Software is HmiSoftware;
            });
        }

        public static PlcSoftware FindPlcSoftware(Device device)
        {
            foreach (var item in AllItems(device))
            {
                var container = item.GetService<SoftwareContainer>();
                var software = container == null ? null : container.Software as PlcSoftware;
                if (software != null) return software;
            }
            return null;
        }

        public static HmiSoftware FindHmiSoftware(Device device)
        {
            foreach (var item in AllItems(device))
            {
                var container = item.GetService<SoftwareContainer>();
                var software = container == null ? null : container.Software as HmiSoftware;
                if (software != null) return software;
            }
            return null;
        }

        public static Node FindFirstNode(Device device)
        {
            foreach (var item in AllItems(device))
            {
                var network = item.GetService<NetworkInterface>();
                if (network == null) continue;
                foreach (var node in network.Nodes) return node;
            }
            return null;
        }

        public static CompileSummary Compile(object target, string label, Report report)
        {
            ICompilable compilable = null;
            var provider = target as IEngineeringServiceProvider;
            if (provider != null)
            {
                try { compilable = provider.GetService<ICompilable>(); }
                catch { }
            }
            if (compilable == null)
            {
                try
                {
                    compilable = Compat.InvokeGenericMethod(target, "GetService", Type.EmptyTypes,
                        new[] { typeof(ICompilable) }, new object[0]) as ICompilable;
                }
                catch { }
            }
            if (compilable == null)
                throw new InvalidOperationException("Object does not provide ICompilable: " + label);

            var result = compilable.Compile();
            var summary = new CompileSummary
            {
                Target = label,
                State = result.State.ToString(),
                ErrorCount = result.ErrorCount,
                WarningCount = result.WarningCount
            };
            CollectMessages(summary, result.Messages, 0);
            report.AddCompile(summary);
            return summary;
        }

        private static void CollectMessages(CompileSummary summary, CompilerResultMessageComposition messages, int depth)
        {
            if (messages == null || depth > 8) return;
            foreach (CompilerResultMessage message in messages)
            {
                if (summary.Messages.Count >= 100) return;
                var indent = new string(' ', depth * 2);
                summary.Messages.Add(indent + message.State + ": " + message.Description);
                CollectMessages(summary, message.Messages, depth + 1);
            }
        }

        public void Dispose()
        {
            try
            {
                if (Project != null)
                {
                    try { Project.Close(); }
                    catch { }
                }
            }
            finally
            {
                if (Portal != null) Portal.Dispose();
            }
        }

        private sealed class VersionComparer : IComparer<string>
        {
            public int Compare(string x, string y)
            {
                var left = Parse(x);
                var right = Parse(y);
                for (var i = 0; i < Math.Max(left.Length, right.Length); i++)
                {
                    var a = i < left.Length ? left[i] : 0;
                    var b = i < right.Length ? right[i] : 0;
                    if (a != b) return a.CompareTo(b);
                }
                return 0;
            }

            private static int[] Parse(string value)
            {
                if (string.IsNullOrWhiteSpace(value)) return new int[0];
                var parts = value.Split(new[] { '.', '-', ' ' }, StringSplitOptions.RemoveEmptyEntries);
                var numbers = new List<int>();
                foreach (var part in parts)
                {
                    int number;
                    if (int.TryParse(part, out number)) numbers.Add(number);
                    else numbers.Add(0);
                }
                return numbers.ToArray();
            }
        }
    }
}
