using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Storage;

namespace Aicepeak.Api.Projects;

/// <summary>What a document's metadata must look like, at the upload URL and when it is added to a project.</summary>
internal static class DocumentRules {
    public const string NameRule = "must be a file name of at most 200 characters ending in .pdf, .doc, .docx, .xls or .xlsx";
    public const string ContentTypeRule = "must be a media type of at most 255 characters";
    public static readonly string SizeRule = $"must be an integer from 1 to {DocumentBlobs.MaxSize}";

    public static readonly string[] Extensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx"];

    /// <summary>A file name only (no path), at most 200 characters, with one of the allowed extensions (any case).</summary>
    public static bool IsValidName(string name) =>
        name.Length <= Document.MaxNameLength
        && !name.Any(character => char.IsControl(character) || character is '/' or '\\')
        && Extensions.Any(extension => name.EndsWith(extension, StringComparison.OrdinalIgnoreCase))
        && !string.IsNullOrWhiteSpace(Path.GetFileNameWithoutExtension(name));

    /// <summary>At least one byte and at most <see cref="DocumentBlobs.MaxSize"/> (50 MB).</summary>
    public static bool IsValidSize(long size) => size is > 0 and <= DocumentBlobs.MaxSize;

    /// <summary>Non-empty, at most 255 characters, no control characters or surrounding spaces.</summary>
    public static bool IsValidContentType(string contentType) =>
        contentType.Length is > 0 and <= Document.MaxContentTypeLength
        && !contentType.Any(char.IsControl)
        && contentType.Trim().Length == contentType.Length;
}
