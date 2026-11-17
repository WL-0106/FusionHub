using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Siemens.Engineering;
using Siemens.Engineering.HmiUnified;
using Siemens.Engineering.HmiUnified.HmiTags;
using Siemens.Engineering.HmiUnified.UI.Screens;
using Siemens.Engineering.HW;
using Siemens.Engineering.HW.Features;

namespace TiaAutoGen
{
    internal static class HmiBuilder
    {
        private static readonly Dictionary<string, string> KnownUiTypes =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "HmiButton", "Siemens.Engineering.HmiUnified.UI.Controls.HmiButton" },
                { "Button", "Siemens.Engineering.HmiUnified.UI.Controls.HmiButton" },
                { "HmiIOField", "Siemens.Engineering.HmiUnified.UI.Controls.HmiIOField" },
                { "IOField", "Siemens.Engineering.HmiUnified.UI.Controls.HmiIOField" },
                { "HmiTextField", "Siemens.Engineering.HmiUnified.UI.Controls.HmiTextField" },
                { "TextField", "Siemens.Engineering.HmiUnified.UI.Controls.HmiTextField" },
                { "HmiScreenWindow", "Siemens.Engineering.HmiUnified.UI.Screens.HmiScreenWindow" },
                { "HmiRectangle", "Siemens.Engineering.HmiUnified.UI.Shapes.HmiRectangle" },
                { "HmiCircle", "Siemens.Engineering.HmiUnified.UI.Shapes.HmiCircle" }
            };

        public static HmiSoftware Build(Project project, HmiSpec spec, Report report)
        {
            var hmiDevice = project.Devices.FirstOrDefault(d =>
                string.Equals(d.Name, spec.DeviceName, StringComparison.OrdinalIgnoreCase));
            if (hmiDevice == null) throw new InvalidOperationException("HMI device not found: " + spec.DeviceName);

            var hmi = TiaSession.FindHmiSoftware(hmiDevice);
            if (hmi == null) throw new InvalidOperationException("No HMI software found in device " + spec.DeviceName);

            var hmiItem = TiaSession.FindHmiItem(hmiDevice);
            var connectionName = EnsureConnection(project, hmiDevice, hmiItem, hmi, spec, report);
            if (connectionName == null)
            {
                report.Warn("HMI connection is not available; HMI tags will be skipped");
            }

            BuildTags(hmi, spec, connectionName, report);
            BuildScreens(hmi, spec, report);
            return hmi;
        }

        private static string EnsureConnection(
            Project project,
            Device hmiDevice,
            DeviceItem hmiItem,
            HmiSoftware hmi,
            HmiSpec spec,
            Report report)
        {
            var desired = string.IsNullOrWhiteSpace(spec.ConnectionName)
                ? spec.DeviceName + "_Connection"
                : spec.ConnectionName;
            var subnetName = string.IsNullOrWhiteSpace(spec.SubnetName)
                ? spec.DeviceName + "_Subnet"
                : spec.SubnetName;

            var plcDevice = project.Devices.FirstOrDefault(d =>
                string.Equals(d.Name, spec.PlcDeviceName, StringComparison.OrdinalIgnoreCase));
            if (plcDevice == null)
            {
                report.Error("HMI " + spec.DeviceName + " references unknown PLC: " + spec.PlcDeviceName);
                return null;
            }

            var management = hmiItem == null ? null : hmiItem.GetService<CommunicationManagement>();
            if (management != null)
            {
                // Re-run safety: reuse an existing HMI connection instead of creating a duplicate.
                foreach (var existing in Compat.Enumerate(management.Connections))
                {
                    if (!string.Equals(existing.GetType().Name, "HmiConnection", StringComparison.OrdinalIgnoreCase)) continue;
                    var existingName = Compat.GetString(existing, "LocalConnectionName");
                    report.Info("reusing HMI connection: " + (existingName ?? desired));
                    return string.IsNullOrWhiteSpace(existingName) ? desired : existingName;
                }
            }

            try
            {
                if (management == null)
                    throw new InvalidOperationException("CommunicationManagement service not found on HMI device item");

                var plcItem = TiaSession.FindPlcItem(plcDevice);
                if (plcItem == null) throw new InvalidOperationException("PLC device item not found for " + plcDevice.Name);

                var localNode = TiaSession.FindFirstNode(hmiDevice);
                var partnerNode = TiaSession.FindFirstNode(plcDevice);
                if (localNode == null || partnerNode == null)
                    throw new InvalidOperationException("No PROFINET/Ethernet node found on PLC or HMI device");

                object subnet = Compat.GetProp(localNode, "ConnectedSubnet");
                if (subnet == null)
                {
                    subnet = Compat.InvokeExtension(localNode, "CreateAndConnectToSubnet",
                        new[] { typeof(string) }, new object[] { subnetName });
                    report.Ok("subnet created: " + subnetName);
                }
                else
                {
                    report.Info("HMI already connected to a subnet");
                }

                if (subnet != null)
                {
                    try
                    {
                        partnerNode.ConnectToSubnet((Subnet)subnet);
                        report.Ok("PLC connected to subnet: " + subnetName);
                    }
                    catch (Exception ex)
                    {
                        report.Warn("PLC subnet connection failed: " + ex.Message);
                    }
                }

                var created = Compat.InvokeGenericExtension(
                    management.Connections,
                    "Create",
                    new[] { typeof(Node), typeof(DeviceItem), typeof(Node) },
                    new[] { typeof(Siemens.Engineering.HW.CommunicationConnections.HmiConnection) },
                    new object[] { localNode, plcItem, partnerNode });

                var name = Compat.GetString(created, "LocalConnectionName");
                report.Ok("HMI connection created: " + (name ?? desired));
                return string.IsNullOrWhiteSpace(name) ? desired : name;
            }
            catch (Exception ex)
            {
                report.Warn("automatic HMI/PLC connection failed: " + ex.Message);
            }

            // Last resort: create an unbound HMI-side connection object.
            try
            {
                var fallback = Compat.CreateTyped(
                    hmi.Connections,
                    typeof(Siemens.Engineering.HmiUnified.HmiConnections.HmiConnection),
                    desired,
                    null);
                if (fallback != null)
                {
                    report.Warn("HMI connection created without an automatically bound PLC partner; " +
                                "open the connection once in TIA Portal and select the PLC.");
                    var name = Compat.GetString(fallback, "Name");
                    return string.IsNullOrWhiteSpace(name) ? desired : name;
                }
            }
            catch (Exception ex)
            {
                report.Error("HMI connection could not be created: " + ex.Message);
            }
            return null;
        }

        private static void BuildTags(HmiSoftware hmi, HmiSpec spec, string connectionName, Report report)
        {
            if (spec.Tags.Count == 0) return;

            var defaultTable = string.IsNullOrWhiteSpace(spec.TagTableName) ? "HmiTags" : spec.TagTableName;
            var tables = new Dictionary<string, HmiTagTable>(StringComparer.OrdinalIgnoreCase);

            foreach (var tagSpec in spec.Tags)
            {
                if (string.IsNullOrWhiteSpace(tagSpec.Name))
                {
                    report.Warn("skipping HMI tag with empty name");
                    continue;
                }
                if (connectionName == null)
                {
                    report.Warn("skipping HMI tag " + tagSpec.Name + ": no connection");
                    continue;
                }

                var tableName = string.IsNullOrWhiteSpace(tagSpec.TagTableName) ? defaultTable : tagSpec.TagTableName;
                HmiTagTable table;
                if (!tables.TryGetValue(tableName, out table))
                {
                    table = hmi.TagTables.Find(tableName);
                    if (table == null)
                    {
                        table = hmi.TagTables.Create(tableName);
                        report.Ok("HMI tag table created: " + tableName);
                    }
                    tables[tableName] = table;
                }

                if (table.Tags.Find(tagSpec.Name) != null)
                {
                    report.Info("HMI tag exists, skipped: " + tagSpec.Name);
                    continue;
                }

                try
                {
                    var created = hmi.Tags.Create(tagSpec.Name, tableName);
                    Compat.SetMember(created, "Connection", connectionName);
                    if (!string.IsNullOrWhiteSpace(tagSpec.PlcTag))
                    {
                        Compat.SetMember(created, "PlcTag", tagSpec.PlcTag);
                    }
                    else if (!string.IsNullOrWhiteSpace(tagSpec.DataType))
                    {
                        Compat.SetMember(created, "DataType", tagSpec.DataType);
                    }
                    report.Ok("HMI tag created: " + tableName + "." + tagSpec.Name);
                }
                catch (Exception ex)
                {
                    report.Error("HMI tag failed: " + tagSpec.Name + " -> " + ex.Message);
                }
            }
        }

        private static void BuildScreens(HmiSoftware hmi, HmiSpec spec, Report report)
        {
            foreach (var screenSpec in spec.Screens)
            {
                if (string.IsNullOrWhiteSpace(screenSpec.Name))
                {
                    report.Warn("skipping screen with empty name");
                    continue;
                }

                object screen = Compat.FindByName(hmi.Screens, screenSpec.Name);
                if (screen == null)
                {
                    try
                    {
                        screen = Compat.CreateTyped(hmi.Screens, typeof(HmiScreen), screenSpec.Name, null);
                        report.Ok("screen created: " + screenSpec.Name);
                    }
                    catch (Exception ex)
                    {
                        report.Error("screen creation failed: " + screenSpec.Name + " -> " + ex.Message);
                        continue;
                    }
                }
                else
                {
                    report.Info("screen exists: " + screenSpec.Name);
                }

                if (screenSpec.Width > 0) Compat.SetMember(screen, "Width", (uint)screenSpec.Width);
                if (screenSpec.Height > 0) Compat.SetMember(screen, "Height", (uint)screenSpec.Height);

                var screenItems = Compat.GetProp(screen, "ScreenItems");
                if (screenItems == null)
                {
                    report.Warn("screen " + screenSpec.Name + " exposes no ScreenItems collection");
                    continue;
                }

                foreach (var itemSpec in screenSpec.Items)
                {
                    if (string.IsNullOrWhiteSpace(itemSpec.Name)) continue;
                    try
                    {
                        var itemType = ResolveUiType(itemSpec.Type);
                        var item = Compat.FindByName(screenItems, itemSpec.Name);
                        if (item == null)
                        {
                            item = Compat.CreateTyped(screenItems, itemType, itemSpec.Name, null);
                            report.Ok("screen item created: " + screenSpec.Name + "." + itemSpec.Name + " (" + itemType.Name + ")");
                        }
                        else
                        {
                            report.Info("screen item exists: " + screenSpec.Name + "." + itemSpec.Name);
                        }

                        if (itemSpec.Left != 0) Compat.SetMember(item, "Left", itemSpec.Left);
                        if (itemSpec.Top != 0) Compat.SetMember(item, "Top", itemSpec.Top);
                        if (itemSpec.Width > 0) Compat.SetMember(item, "Width", (uint)itemSpec.Width);
                        if (itemSpec.Height > 0) Compat.SetMember(item, "Height", (uint)itemSpec.Height);
                        if (!string.IsNullOrWhiteSpace(itemSpec.Text)) Compat.SetMember(item, "Text", itemSpec.Text);

                        foreach (var property in itemSpec.Properties)
                        {
                            if (!Compat.SetMember(item, property.Key, property.Value))
                                report.Warn("attribute not applied: " + itemSpec.Name + "." + property.Key);
                        }
                    }
                    catch (Exception ex)
                    {
                        report.Error("screen item failed: " + screenSpec.Name + "." + itemSpec.Name + " -> " + ex.Message);
                    }
                }
            }
        }

        private static Type ResolveUiType(string name)
        {
            var requested = string.IsNullOrWhiteSpace(name) ? "HmiButton" : name;
            string fullName;
            if (!KnownUiTypes.TryGetValue(requested, out fullName)) fullName = requested;

            var type = Type.GetType(fullName, false);
            if (type != null) return type;

            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var assemblyName = assembly.GetName().Name;
                if (assemblyName == null || !assemblyName.StartsWith("Siemens.Engineering", StringComparison.OrdinalIgnoreCase))
                    continue;
                try
                {
                    type = assembly.GetType(fullName, false);
                    if (type != null) return type;
                }
                catch { }
            }

            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!assembly.GetName().Name.StartsWith("Siemens.Engineering", StringComparison.OrdinalIgnoreCase)) continue;
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
                catch { continue; }
                type = types.FirstOrDefault(t => string.Equals(t.Name, requested, StringComparison.OrdinalIgnoreCase));
                if (type != null) return type;
            }

            throw new InvalidOperationException("Unknown HMI control type: " + requested);
        }
    }
}
