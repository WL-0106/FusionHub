using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;

namespace TiaAutoGen
{
    public sealed class CompileSummary
    {
        public string Target { get; set; }
        public string State { get; set; }
        public int ErrorCount { get; set; }
        public int WarningCount { get; set; }
        public List<string> Messages { get; set; } = new List<string>();

        public bool Failed
        {
            get { return ErrorCount > 0 || string.Equals(State, "Error", StringComparison.OrdinalIgnoreCase); }
        }
    }

    public sealed class Report
    {
        private readonly List<string> _lines = new List<string>();

        public bool DryRun { get; set; }
        public string StartedAt { get; set; } = DateTime.Now.ToString("s");
        public string FinishedAt { get; set; }
        public string ProjectFile { get; set; }
        public string OpennessVersion { get; set; }
        public int Errors { get; private set; }
        public int Warnings { get; private set; }
        public int CompileErrors { get; private set; }
        public List<string> Steps { get; private set; } = new List<string>();
        public List<CompileSummary> Compilations { get; private set; } = new List<CompileSummary>();

        public Report()
        {
            try
            {
                OpennessVersion = typeof(Siemens.Engineering.TiaPortal).Assembly.GetName().Version.ToString();
            }
            catch (Exception ex)
            {
                OpennessVersion = "unavailable (" + ex.GetType().Name + ")";
            }
        }

        public void Step(string message)
        {
            Write("[step] " + message);
        }

        public void Info(string message)
        {
            Write("[info] " + message);
        }

        public void Ok(string message)
        {
            Write("[ ok ] " + message);
        }

        public void Warn(string message)
        {
            Warnings++;
            Write("[warn] " + message);
        }

        public void Error(string message)
        {
            Errors++;
            Write("[err ] " + message);
        }

        public void AddCompile(CompileSummary summary)
        {
            Compilations.Add(summary);
            if (summary.Failed)
            {
                CompileErrors += Math.Max(1, summary.ErrorCount);
                Write("[err ] compile " + summary.Target + " failed: " + summary.ErrorCount + " error(s)");
            }
            else if (summary.WarningCount > 0)
            {
                Write("[warn] compile " + summary.Target + " finished with " + summary.WarningCount + " warning(s)");
            }
            else
            {
                Write("[ ok ] compile " + summary.Target + " succeeded");
            }
        }

        public int ExitCode
        {
            get
            {
                if (Errors > 0 || CompileErrors > 0) return 3;
                return 0;
            }
        }

        public void Save(string path)
        {
            FinishedAt = DateTime.Now.ToString("s");
            try
            {
                var json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
                File.WriteAllText(path, json.Serialize(this));
                Info("report written to " + path);
            }
            catch (Exception ex)
            {
                Warn("could not write report: " + ex.Message);
            }
        }

        private void Write(string line)
        {
            _lines.Add(DateTime.Now.ToString("HH:mm:ss") + " " + line);
            Console.WriteLine(line);
        }
    }
}
