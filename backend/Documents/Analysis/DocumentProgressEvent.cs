using System.Text.Json.Serialization;

namespace Aicepeak.Api.Documents.Analysis;

/// <summary>
/// One server-sent event of a validation or extraction run. <see cref="Document"/> is the document ID, or empty for the
/// run itself. <see cref="OverallProgress"/> 100 comes exactly once, in the last event. An <see cref="Error"/> marks
/// the document invalid, or with an empty <see cref="Document"/> a failed run. Null fields are not sent.
/// </summary>
/// <param name="Positions">Extraction only: positions found so far in the whole run.</param>
public sealed record DocumentProgressEvent(
    int OverallProgress,
    string Document,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? DocumentProgress = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Error = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? Pages = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? PagesRead = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? Positions = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] ExtractedPosition? Position = null);

/// <summary>A financial position found in a document: its value for a period, with the document and page as source.</summary>
public sealed record ExtractedPosition(string Name, decimal Value, string Period, string Source, int Page);
