using System.Collections.Generic;

namespace TiaAutoGen
{
    /// <summary>
    /// Declarative description of the TIA Portal project that should be produced.
    /// Deserialized from JSON with JavaScriptSerializer (net48, no external packages).
    /// </summary>
    public sealed class ProjectSpec
    {
        /// <summary>Name of the .ap20/.ap21 project. Required when creating a new project.</summary>
        public string ProjectName { get; set; }

        /// <summary>Folder that will contain the new project. Relative paths are resolved against the spec file.</summary>
        public string ProjectDirectory { get; set; }

        /// <summary>Optional existing .ap20/.ap21 file. When set, the project is opened instead of created.</summary>
        public string OpenProjectPath { get; set; }

        /// <summary>Start TIA Portal with a visible UI instead of headless mode.</summary>
        public bool WithUserInterface { get; set; }

        /// <summary>Compile PLC/HMI after generation. Default true.</summary>
        public bool Compile { get; set; } = true;

        /// <summary>Save the project after generation. Default true.</summary>
        public bool Save { get; set; } = true;

        /// <summary>Abort on the first item error instead of collecting all errors. Default false.</summary>
        public bool Strict { get; set; }

        /// <summary>PLC devices to create.</summary>
        public List<PlcSpec> Plcs { get; set; } = new List<PlcSpec>();

        /// <summary>HMI devices to create.</summary>
        public List<HmiSpec> Hmis { get; set; } = new List<HmiSpec>();
    }

    /// <summary>Common hardware selection fields. TypeIdentifier wins over catalog lookup when both are set.</summary>
    public class DeviceSpec
    {
        /// <summary>Device name inside the project, e.g. PLC_1.</summary>
        public string DeviceName { get; set; }

        /// <summary>Hardware catalog keyword, e.g. "CPU 1511-1 PN".</summary>
        public string CatalogName { get; set; }

        /// <summary>Optional exact catalog type name filter, e.g. "CPU 1511-1 PN".</summary>
        public string TypeName { get; set; }

        /// <summary>Optional exact Openness type identifier, e.g. "OrderNumber:6ES7 511-1AK02-0AB0/V3.1".</summary>
        public string TypeIdentifier { get; set; }
    }

    public sealed class PlcSpec : DeviceSpec
    {
        /// <summary>PLC tag tables to create/update.</summary>
        public List<TagTableSpec> TagTables { get; set; } = new List<TagTableSpec>();

        /// <summary>SCL source files that are imported and compiled into program blocks.</summary>
        public List<SourceSpec> Sources { get; set; } = new List<SourceSpec>();
    }

    public sealed class HmiSpec : DeviceSpec
    {
        /// <summary>DeviceName of the PLC this HMI communicates with.</summary>
        public string PlcDeviceName { get; set; }

        /// <summary>Name of the HMI connection. Default: &lt;DeviceName&gt;_Connection.</summary>
        public string ConnectionName { get; set; }

        /// <summary>Name of the PROFINET subnet created for the connection. Default: &lt;DeviceName&gt;_Subnet.</summary>
        public string SubnetName { get; set; }

        /// <summary>HMI tag table that receives the tags below. Default: HmiTags.</summary>
        public string TagTableName { get; set; } = "HmiTags";

        /// <summary>HMI tags bound to PLC tags.</summary>
        public List<HmiTagSpec> Tags { get; set; } = new List<HmiTagSpec>();

        /// <summary>Screens and simple screen items to create.</summary>
        public List<ScreenSpec> Screens { get; set; } = new List<ScreenSpec>();
    }

    public sealed class TagTableSpec
    {
        public string Name { get; set; }
        public List<TagSpec> Tags { get; set; } = new List<TagSpec>();
    }

    public sealed class TagSpec
    {
        public string Name { get; set; }

        /// <summary>SCL data type, e.g. Bool, Int, Real, String, or a UDT name.</summary>
        public string DataType { get; set; }

        /// <summary>Absolute address such as %M0.0 / %IW64. Optional for optimized blocks.</summary>
        public string Address { get; set; }
    }

    public sealed class SourceSpec
    {
        /// <summary>External source name shown in TIA Portal.</summary>
        public string Name { get; set; }

        /// <summary>Path to a .scl file. Relative paths are resolved against the spec file.</summary>
        public string Path { get; set; }

        /// <summary>Inline SCL content. Used when Path is empty.</summary>
        public string Content { get; set; }
    }

    public sealed class HmiTagSpec
    {
        public string Name { get; set; }

        /// <summary>Symbolic PLC tag name, e.g. "IO_Tags".MotorStart or DB_MotorData.RunSeconds.</summary>
        public string PlcTag { get; set; }

        /// <summary>Optional HMI data type. Leave empty when PlcTag is symbolic.</summary>
        public string DataType { get; set; }

        /// <summary>Optional tag table override.</summary>
        public string TagTableName { get; set; }
    }

    public sealed class ScreenSpec
    {
        public string Name { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public List<ScreenItemSpec> Items { get; set; } = new List<ScreenItemSpec>();
    }

    public sealed class ScreenItemSpec
    {
        public string Name { get; set; }

        /// <summary>Short name (HmiButton, HmiIOField, ...) or a full Openness type name.</summary>
        public string Type { get; set; } = "HmiButton";

        public int Left { get; set; }
        public int Top { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }

        /// <summary>Optional text, only applied when the target control exposes a writable string attribute.</summary>
        public string Text { get; set; }

        /// <summary>Additional attributes, applied best-effort (e.g. "BackColor": "#FF00FF00").</summary>
        public Dictionary<string, object> Properties { get; set; } = new Dictionary<string, object>();
    }
}
