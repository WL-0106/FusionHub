using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;
using Siemens.Engineering;
using Siemens.Engineering.HmiUnified;
using Siemens.Engineering.HW;
using Siemens.Engineering.SW;

namespace TiaAutoGen
{
    internal static class Program
    {
        private const string SampleJson = @"{
  ""ProjectName"": ""DemoLine"",
  ""ProjectDirectory"": ""projects"",
  ""WithUserInterface"": false,
  ""Compile"": true,
  ""Save"": true,
  ""Strict"": false,

  ""Plcs"": [
    {
      ""DeviceName"": ""PLC_1"",
      ""CatalogName"": ""CPU 1511-1 PN"",
      ""TypeName"": ""CPU 1511-1 PN"",
      ""TagTables"": [
        {
          ""Name"": ""IO_Tags"",
          ""Tags"": [
            { ""Name"": ""MotorStart"", ""DataType"": ""Bool"", ""Address"": ""%M0.0"" },
            { ""Name"": ""MotorStop"",  ""DataType"": ""Bool"", ""Address"": ""%M0.1"" },
            { ""Name"": ""MotorRun"",   ""DataType"": ""Bool"", ""Address"": ""%M0.2"" },
            { ""Name"": ""SpeedSetpoint"", ""DataType"": ""Int"", ""Address"": ""%MW10"" }
          ]
        }
      ],
      ""Sources"": [
        { ""Name"": ""MotorControl"", ""Path"": ""scl/MotorControl.scl"" },
        { ""Name"": ""ConveyorLogic"", ""Path"": ""scl/ConveyorLogic.scl"" }
      ]
    }
  ],

  ""Hmis"": [
    {
      ""DeviceName"": ""HMI_1"",
      ""CatalogName"": ""Unified Comfort Panel"",
      ""TypeName"": ""6AV2128-3QB06-0AX0"",
      ""PlcDeviceName"": ""PLC_1"",
      ""ConnectionName"": ""HMI_Connection"",
      ""SubnetName"": ""PN_Subnet"",
      ""TagTableName"": ""HmiTags"",
      ""Tags"": [
        { ""Name"": ""MotorRun"", ""PlcTag"": ""\""IO_Tags\"".MotorRun"" },
        { ""Name"": ""SpeedSetpoint"", ""PlcTag"": ""\""IO_Tags\"".SpeedSetpoint"" }
      ],
      ""Screens"": [
        {
          ""Name"": ""MainScreen"",
          ""Width"": 1920,
          ""Height"": 1080,
          ""Items"": [
            { ""Name"": ""BtnStart"", ""Type"": ""HmiButton"", ""Left"": 80, ""Top"": 80, ""Width"": 200, ""Height"": 60, ""Text"": ""START"" },
            { ""Name"": ""BtnStop"",  ""Type"": ""HmiButton"", ""Left"": 320, ""Top"": 80, ""Width"": 200, ""Height"": 60, ""Text"": ""STOP"" },
            { ""Name"": ""IoRun"",    ""Type"": ""HmiIOField"", ""Left"": 80, ""Top"": 200, ""Width"": 200, ""Height"": 50 },
            { ""Name"": ""IoSpeed"",  ""Type"": ""HmiIOField"", ""Left"": 320, ""Top"": 200, ""Width"": 200, ""Height"": 50 }
          ]
        }
      ]
    }
  ]
}";

        private static int Main(string[] args)
        {
            if (args.Length == 0)
            {
                Usage();
                return 1;
            }

            var command = args[0].ToLowerInvariant();
            try
            {
                switch (command)
                {
                    case "generate":
                        return Generate(args.Skip(1).ToArray());
                    case "catalog":
                        return Catalog(args.Skip(1).ToArray());
                    case "doctor":
                        return Doctor();
                    case "sample":
                        return Sample();
                    case "help":
                    case "--help":
                    case "-h":
                        Usage();
                        return 0;
                    default:
                        Console.Error.WriteLine("Unknown command: " + command);
                        Usage();
                        return 1;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("[fatal] " + ex.Message);
                return 2;
            }
        }

        private static int Generate(string[] args)
        {
            if (args.Length == 0 || args[0].StartsWith("--", StringComparison.Ordinal))
            {
                Console.Error.WriteLine("Usage: TiaAutoGen generate <spec.json> [options]");
                return 1;
            }

            var specPath = Path.GetFullPath(args[0]);
            if (!File.Exists(specPath))
            {
                Console.Error.WriteLine("[fatal] spec not found: " + specPath);
                return 1;
            }

            var withUi = HasFlag(args, "--ui");
            var dryRun = HasFlag(args, "--dry-run");
            var noCompile = HasFlag(args, "--no-compile");
            var noSave = HasFlag(args, "--no-save");
            var strict = HasFlag(args, "--strict");

            var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
            var spec = serializer.Deserialize<ProjectSpec>(File.ReadAllText(specPath));
            if (spec == null) throw new InvalidOperationException("spec is empty");
            Normalize(spec);

            var baseDir = Path.GetDirectoryName(specPath);
            ResolvePaths(spec, baseDir);
            spec.WithUserInterface = spec.WithUserInterface || withUi;
            spec.Compile = spec.Compile && !noCompile;
            spec.Save = spec.Save && !noSave;
            spec.Strict = spec.Strict || strict;

            var validation = Validate(spec);
            if (validation.Count > 0)
            {
                foreach (var error in validation) Console.Error.WriteLine("[spec] " + error);
                return 1;
            }

            var report = new Report { DryRun = dryRun };
            var reportPath = Path.Combine(baseDir, "TiaAutoGen.report.json");
            var workDir = Path.Combine(baseDir, "TiaAutoGen.work");

            if (dryRun)
            {
                DryRun(spec, report, workDir);
                report.Save(reportPath);
                return report.ExitCode;
            }

            try
            {
                Run(spec, report, workDir);
            }
            catch (Exception ex)
            {
                report.Error("aborted: " + ex.Message);
            }
            finally
            {
                report.Save(reportPath);
            }
            return report.ExitCode;
        }

        private static void Run(ProjectSpec spec, Report report, string workDir)
        {
            using (var session = new TiaSession(spec.WithUserInterface))
            {
                report.Step("opening TIA Portal project");
                session.OpenOrCreate(spec);
                var project = session.Project;
                var actualPath = Compat.GetString(project, "Path");
                report.ProjectFile = !string.IsNullOrWhiteSpace(actualPath)
                    ? actualPath
                    : (string.IsNullOrWhiteSpace(spec.OpenProjectPath)
                        ? Path.Combine(spec.ProjectDirectory, spec.ProjectName + ".ap21")
                        : spec.OpenProjectPath);
                report.Ok("project ready: " + report.ProjectFile);

                var devices = new Dictionary<string, Device>(StringComparer.OrdinalIgnoreCase);

                foreach (var plc in spec.Plcs)
                {
                    report.Step("adding PLC " + plc.DeviceName);
                    var typeId = TiaSession.ResolveTypeIdentifier(session.Portal, plc, report);
                    devices[plc.DeviceName] = session.AddDevice(typeId, plc.DeviceName, report);
                }

                foreach (var hmi in spec.Hmis)
                {
                    report.Step("adding HMI " + hmi.DeviceName);
                    var typeId = TiaSession.ResolveTypeIdentifier(session.Portal, hmi, report);
                    devices[hmi.DeviceName] = session.AddDevice(typeId, hmi.DeviceName, report);
                }

                var plcSoftware = new Dictionary<string, PlcSoftware>(StringComparer.OrdinalIgnoreCase);
                foreach (var plc in spec.Plcs)
                {
                    report.Step("generating PLC software for " + plc.DeviceName);
                    try
                    {
                        plcSoftware[plc.DeviceName] = PlcBuilder.Build(project, plc, report, workDir);
                    }
                    catch (Exception ex)
                    {
                        report.Error("PLC generation failed: " + plc.DeviceName + " -> " + ex.Message);
                        if (spec.Strict) throw;
                    }
                }

                var hmiSoftware = new Dictionary<string, HmiSoftware>(StringComparer.OrdinalIgnoreCase);
                foreach (var hmi in spec.Hmis)
                {
                    report.Step("generating HMI software for " + hmi.DeviceName);
                    try
                    {
                        hmiSoftware[hmi.DeviceName] = HmiBuilder.Build(project, hmi, report);
                    }
                    catch (Exception ex)
                    {
                        report.Error("HMI generation failed: " + hmi.DeviceName + " -> " + ex.Message);
                        if (spec.Strict) throw;
                    }
                }

                if (spec.Compile)
                {
                    CompileAll(project, spec, plcSoftware, hmiSoftware, report);
                }
                else
                {
                    report.Info("compile skipped (--no-compile)");
                }

                if (spec.Save)
                {
                    report.Step("saving project");
                    project.Save();
                    report.Ok("project saved");
                }
                else
                {
                    report.Info("save skipped (--no-save)");
                }
            }
        }

        private static void CompileAll(
            Project project,
            ProjectSpec spec,
            IDictionary<string, PlcSoftware> plcSoftware,
            IDictionary<string, HmiSoftware> hmiSoftware,
            Report report)
        {
            report.Step("compiling");

            foreach (var plc in spec.Plcs)
            {
                PlcSoftware software;
                if (plcSoftware.TryGetValue(plc.DeviceName, out software))
                {
                    try { TiaSession.Compile(software, "PLC software " + plc.DeviceName, report); }
                    catch (Exception ex) { report.Error("compile failed: " + plc.DeviceName + " software -> " + ex.Message); }
                }

                var device = project.Devices.FirstOrDefault(d =>
                    string.Equals(d.Name, plc.DeviceName, StringComparison.OrdinalIgnoreCase));
                if (device != null)
                {
                    try { TiaSession.Compile(device, "PLC hardware " + plc.DeviceName, report); }
                    catch (Exception ex) { report.Warn("hardware compile failed: " + plc.DeviceName + " -> " + ex.Message); }
                }
            }

            foreach (var hmi in spec.Hmis)
            {
                var device = project.Devices.FirstOrDefault(d =>
                    string.Equals(d.Name, hmi.DeviceName, StringComparison.OrdinalIgnoreCase));
                if (device == null) continue;

                var hmiItem = TiaSession.FindHmiItem(device);
                HmiSoftware software;
                hmiSoftware.TryGetValue(hmi.DeviceName, out software);

                if (hmiItem != null)
                {
                    try { TiaSession.Compile(hmiItem, "HMI hardware " + hmi.DeviceName, report); }
                    catch (Exception ex) { report.Warn("HMI hardware compile failed: " + hmi.DeviceName + " -> " + ex.Message); }
                }

                if (software != null)
                {
                    try { TiaSession.Compile(software, "HMI software " + hmi.DeviceName, report); }
                    catch (Exception ex) { report.Warn("HMI software compile failed: " + hmi.DeviceName + " -> " + ex.Message); }
                }
            }
        }

        private static void DryRun(ProjectSpec spec, Report report, string workDir)
        {
            report.Step("dry run: validating spec and materializing sources");
            var outDir = Path.Combine(Path.GetDirectoryName(workDir), "TiaAutoGen.out");
            Directory.CreateDirectory(outDir);

            foreach (var plc in spec.Plcs)
            {
                foreach (var table in plc.TagTables)
                {
                    report.Info("PLC " + plc.DeviceName + " tag table " + table.Name + ": " + table.Tags.Count + " tag(s)");
                }

                foreach (var source in plc.Sources)
                {
                    var text = !string.IsNullOrWhiteSpace(source.Content)
                        ? source.Content
                        : File.ReadAllText(source.Path);
                    var name = string.IsNullOrWhiteSpace(source.Name) ? "source" : source.Name;
                    var target = Path.Combine(outDir, name + ".scl");
                    File.WriteAllText(target, text, new System.Text.UTF8Encoding(true));
                    report.Ok("SCL staged: " + target);
                }
            }

            foreach (var hmi in spec.Hmis)
            {
                report.Info("HMI " + hmi.DeviceName + " -> PLC " + hmi.PlcDeviceName +
                            ", tags " + hmi.Tags.Count + ", screens " + hmi.Screens.Count);
            }

            var plan = new
            {
                spec = spec,
                generatedAt = DateTime.Now.ToString("s"),
                note = "Dry run only. Nothing was written to TIA Portal."
            };
            var planPath = Path.Combine(outDir, "plan.json");
            File.WriteAllText(planPath, new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Serialize(plan));
            report.Ok("plan written: " + planPath);
        }

        private static List<string> Validate(ProjectSpec spec)
        {
            var errors = new List<string>();

            if (string.IsNullOrWhiteSpace(spec.OpenProjectPath))
            {
                if (string.IsNullOrWhiteSpace(spec.ProjectName)) errors.Add("ProjectName is required");
                if (string.IsNullOrWhiteSpace(spec.ProjectDirectory)) errors.Add("ProjectDirectory is required");
            }
            else if (!File.Exists(spec.OpenProjectPath))
            {
                errors.Add("OpenProjectPath does not exist: " + spec.OpenProjectPath);
            }

            if (spec.Plcs.Count == 0 && spec.Hmis.Count == 0)
                errors.Add("at least one PLC or HMI device is required");

            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var plc in spec.Plcs)
            {
                ValidateDevice(plc, "PLC", names, errors);
                foreach (var table in plc.TagTables)
                {
                    if (string.IsNullOrWhiteSpace(table.Name)) errors.Add("PLC " + plc.DeviceName + ": tag table name is required");
                    foreach (var tag in table.Tags)
                    {
                        if (string.IsNullOrWhiteSpace(tag.Name)) errors.Add("PLC " + plc.DeviceName + ": tag name is required");
                        if (string.IsNullOrWhiteSpace(tag.DataType)) errors.Add("PLC " + plc.DeviceName + ": tag " + tag.Name + " has no DataType");
                    }
                }
                foreach (var source in plc.Sources)
                {
                    if (string.IsNullOrWhiteSpace(source.Path) && string.IsNullOrWhiteSpace(source.Content))
                        errors.Add("PLC " + plc.DeviceName + ": source needs Path or Content");
                    if (!string.IsNullOrWhiteSpace(source.Path) && !File.Exists(source.Path))
                        errors.Add("PLC " + plc.DeviceName + ": SCL not found: " + source.Path);
                }
            }

            foreach (var hmi in spec.Hmis)
            {
                ValidateDevice(hmi, "HMI", names, errors);
                if (string.IsNullOrWhiteSpace(hmi.PlcDeviceName))
                    errors.Add("HMI " + hmi.DeviceName + ": PlcDeviceName is required");
                else if (!spec.Plcs.Any(p => string.Equals(p.DeviceName, hmi.PlcDeviceName, StringComparison.OrdinalIgnoreCase)))
                    errors.Add("HMI " + hmi.DeviceName + ": PlcDeviceName not found in Plcs: " + hmi.PlcDeviceName);

                foreach (var tag in hmi.Tags)
                {
                    if (string.IsNullOrWhiteSpace(tag.Name)) errors.Add("HMI " + hmi.DeviceName + ": tag name is required");
                }
                foreach (var screen in hmi.Screens)
                {
                    if (string.IsNullOrWhiteSpace(screen.Name)) errors.Add("HMI " + hmi.DeviceName + ": screen name is required");
                    foreach (var item in screen.Items)
                    {
                        if (string.IsNullOrWhiteSpace(item.Name))
                            errors.Add("HMI " + hmi.DeviceName + ": screen item name is required on " + screen.Name);
                    }
                }
            }

            return errors;
        }

        private static void Normalize(ProjectSpec spec)
        {
            spec.Plcs = spec.Plcs ?? new List<PlcSpec>();
            spec.Hmis = spec.Hmis ?? new List<HmiSpec>();

            foreach (var plc in spec.Plcs)
            {
                plc.TagTables = plc.TagTables ?? new List<TagTableSpec>();
                plc.Sources = plc.Sources ?? new List<SourceSpec>();
                foreach (var table in plc.TagTables) table.Tags = table.Tags ?? new List<TagSpec>();
            }

            foreach (var hmi in spec.Hmis)
            {
                hmi.Tags = hmi.Tags ?? new List<HmiTagSpec>();
                hmi.Screens = hmi.Screens ?? new List<ScreenSpec>();
                foreach (var screen in hmi.Screens)
                {
                    screen.Items = screen.Items ?? new List<ScreenItemSpec>();
                    foreach (var item in screen.Items)
                        item.Properties = item.Properties ?? new Dictionary<string, object>();
                }
            }
        }

        private static void ValidateDevice(DeviceSpec device, string kind, HashSet<string> names, List<string> errors)
        {
            if (string.IsNullOrWhiteSpace(device.DeviceName))
            {
                errors.Add(kind + ": DeviceName is required");
                return;
            }
            if (!names.Add(device.DeviceName))
                errors.Add(kind + ": duplicate DeviceName " + device.DeviceName);
            if (string.IsNullOrWhiteSpace(device.CatalogName) &&
                string.IsNullOrWhiteSpace(device.TypeName) &&
                string.IsNullOrWhiteSpace(device.TypeIdentifier))
            {
                errors.Add(kind + " " + device.DeviceName + ": CatalogName, TypeName or TypeIdentifier is required");
            }
        }

        private static void ResolvePaths(ProjectSpec spec, string baseDir)
        {
            spec.ProjectDirectory = FullPath(spec.ProjectDirectory, baseDir);
            spec.OpenProjectPath = FullPath(spec.OpenProjectPath, baseDir);
            foreach (var plc in spec.Plcs)
            {
                foreach (var source in plc.Sources)
                {
                    source.Path = FullPath(source.Path, baseDir);
                }
            }
        }

        private static string FullPath(string value, string baseDir)
        {
            if (string.IsNullOrWhiteSpace(value)) return value;
            return Path.GetFullPath(Path.Combine(baseDir, value));
        }

        private static bool HasFlag(IEnumerable<string> args, string flag)
        {
            return args.Any(a => string.Equals(a, flag, StringComparison.OrdinalIgnoreCase));
        }

        private static int Catalog(string[] args)
        {
            var keyword = args.Length > 0 ? args[0] : null;
            if (string.IsNullOrWhiteSpace(keyword))
            {
                Console.Error.WriteLine("Usage: TiaAutoGen catalog <keyword>   e.g. catalog \"CPU 1511\"");
                return 1;
            }

            using (var session = new TiaSession(false))
            {
                var report = new Report();
                var entries = session.Portal.HardwareCatalog.Find(keyword);
                var count = 0;
                Console.WriteLine("TypeName\tVersion\tTypeIdentifier\tCatalogPath");
                foreach (var entry in entries)
                {
                    count++;
                    Console.WriteLine(string.Join("\t", new[]
                    {
                        Compat.GetString(entry, "TypeName"),
                        Compat.GetString(entry, "Version"),
                        Compat.GetString(entry, "TypeIdentifier"),
                        Compat.GetString(entry, "CatalogPath")
                    }));
                }
                report.Ok(count + " catalog entrie(s) matched '" + keyword + "'");
            }
            return 0;
        }

        private static int Doctor()
        {
            Console.WriteLine("TiaAutoGen doctor");
            Console.WriteLine("  OS          : " + Environment.OSVersion);
            Console.WriteLine("  64-bit proc : " + Environment.Is64BitProcess);
            try
            {
                var assembly = typeof(Siemens.Engineering.TiaPortal).Assembly;
                Console.WriteLine("  Openness DLL: " + assembly.Location);
                Console.WriteLine("  Openness ver: " + assembly.GetName().Version);
            }
            catch (Exception ex)
            {
                Console.WriteLine("  Openness DLL: NOT LOADABLE (" + ex.Message + ")");
            }

            try
            {
                var processes = Siemens.Engineering.TiaPortal.GetProcesses();
                Console.WriteLine("  TIA processes: " + processes.Count);
                foreach (var process in processes)
                {
                    try
                    {
                        Console.WriteLine("    PID " + process.Id + " | " + process.Mode + " | " + process.ProjectPath);
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("    PID " + process.Id + " | details unavailable (" + ex.Message + ")");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("  TIA processes: unavailable (" + ex.Message + ")");
            }

            Console.WriteLine("  Reminder: the current Windows user must belong to the local group 'Siemens TIA Openness'.");
            return 0;
        }

        private static int Sample()
        {
            var path = Path.Combine(Environment.CurrentDirectory, "spec.sample.json");
            File.WriteAllText(path, SampleJson);
            Console.WriteLine("Sample spec written to " + path);
            return 0;
        }

        private static void Usage()
        {
            Console.WriteLine(@"TiaAutoGen - spec driven TIA Portal project generator (PLC + HMI)

  TiaAutoGen generate <spec.json> [--ui] [--dry-run] [--no-compile] [--no-save] [--strict]
  TiaAutoGen catalog  <keyword>        list hardware catalog matches (e.g. ""CPU 1511"")
  TiaAutoGen doctor                    show Openness environment / running TIA processes
  TiaAutoGen sample                    write spec.sample.json to the current directory

Notes
  * Requires Windows + TIA Portal V20/V21 + membership in local group ""Siemens TIA Openness"".
  * Build: dotnet build -c Release /p:TiaVersion=21
  * A run writes TiaAutoGen.report.json next to the spec.
  * Exit codes: 0 ok, 1 spec/CLI error, 2 fatal, 3 generation/compile errors.");
        }
    }
}
