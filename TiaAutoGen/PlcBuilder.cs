using System;
using System.IO;
using System.Linq;
using Siemens.Engineering;
using Siemens.Engineering.HW;
using Siemens.Engineering.SW;
using Siemens.Engineering.SW.ExternalSources;

namespace TiaAutoGen
{
    internal static class PlcBuilder
    {
        public static PlcSoftware Build(Project project, PlcSpec spec, Report report, string workDir)
        {
            var device = project.Devices.FirstOrDefault(d => string.Equals(d.Name, spec.DeviceName, StringComparison.OrdinalIgnoreCase));
            if (device == null) throw new InvalidOperationException("PLC device not found: " + spec.DeviceName);

            var plc = TiaSession.FindPlcSoftware(device);
            if (plc == null) throw new InvalidOperationException("No PLC software found in device " + spec.DeviceName);

            BuildTagTables(plc, spec, report);
            BuildSources(plc, spec, report, workDir);
            return plc;
        }

        private static void BuildTagTables(PlcSoftware plc, PlcSpec spec, Report report)
        {
            foreach (var tableSpec in spec.TagTables)
            {
                if (string.IsNullOrWhiteSpace(tableSpec.Name))
                {
                    report.Warn("skipping PLC tag table with empty name");
                    continue;
                }

                var table = plc.TagTableGroup.TagTables.Find(tableSpec.Name);
                if (table == null)
                {
                    table = plc.TagTableGroup.TagTables.Create(tableSpec.Name);
                    report.Ok("PLC tag table created: " + tableSpec.Name);
                }
                else
                {
                    report.Info("PLC tag table exists: " + tableSpec.Name);
                }

                foreach (var tag in tableSpec.Tags)
                {
                    if (string.IsNullOrWhiteSpace(tag.Name) || string.IsNullOrWhiteSpace(tag.DataType))
                    {
                        report.Warn("skipping PLC tag with missing Name/DataType in table " + tableSpec.Name);
                        continue;
                    }

                    if (table.Tags.Find(tag.Name) != null)
                    {
                        report.Info("PLC tag exists, skipped: " + tableSpec.Name + "." + tag.Name);
                        continue;
                    }

                    try
                    {
                        table.Tags.Create(tag.Name, tag.DataType, tag.Address ?? string.Empty);
                        report.Ok("PLC tag created: " + tableSpec.Name + "." + tag.Name + " : " + tag.DataType);
                    }
                    catch (Exception ex)
                    {
                        report.Error("PLC tag failed: " + tableSpec.Name + "." + tag.Name + " -> " + ex.Message);
                    }
                }
            }
        }

        private static void BuildSources(PlcSoftware plc, PlcSpec spec, Report report, string workDir)
        {
            foreach (var source in spec.Sources)
            {
                var path = MaterializeSource(source, report, workDir);
                if (path == null) continue;

                var baseName = string.IsNullOrWhiteSpace(source.Name)
                    ? Path.GetFileNameWithoutExtension(path)
                    : source.Name;
                var sourceName = "TiaAutoGen_" + Sanitize(baseName);
                if (sourceName.Length > 120) sourceName = sourceName.Substring(0, 120);

                try
                {
                    var existing = plc.ExternalSourceGroup.ExternalSources
                        .FirstOrDefault(x => string.Equals(Compat.GetString(x, "Name"), sourceName, StringComparison.OrdinalIgnoreCase));
                    if (existing != null) existing.Delete();

                    var external = plc.ExternalSourceGroup.ExternalSources.CreateFromFile(sourceName, path);
                    var generated = external.GenerateBlocksFromSource(GenerateBlockOption.None);
                    var count = generated == null ? 0 : generated.Count;
                    report.Ok("SCL generated " + count + " object(s) from " + Path.GetFileName(path));

                    try { external.Delete(); }
                    catch { }
                }
                catch (Exception ex)
                {
                    report.Error("SCL import failed for " + Path.GetFileName(path) + " -> " + ex.Message);
                }
            }
        }

        private static string MaterializeSource(SourceSpec source, Report report, string workDir)
        {
            if (!string.IsNullOrWhiteSpace(source.Content))
            {
                var directory = Path.Combine(workDir, "generated");
                Directory.CreateDirectory(directory);
                var name = string.IsNullOrWhiteSpace(source.Name) ? "source_" + Guid.NewGuid().ToString("N") : Sanitize(source.Name);
                var path = Path.Combine(directory, name + ".scl");
                File.WriteAllText(path, source.Content, new System.Text.UTF8Encoding(true));
                report.Info("inline SCL written to " + path);
                return path;
            }

            if (!string.IsNullOrWhiteSpace(source.Path) && File.Exists(source.Path)) return source.Path;

            report.Error("SCL source not found: " + (source.Path ?? source.Name));
            return null;
        }

        private static string Sanitize(string value)
        {
            var chars = value.Select(c => char.IsLetterOrDigit(c) || c == '_' ? c : '_').ToArray();
            return new string(chars);
        }
    }
}
