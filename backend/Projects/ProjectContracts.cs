namespace Aicepeak.Api.Projects;

/// <summary>A project as the API returns it; documents are embedded, never a resource of their own.</summary>
public sealed record ProjectResponse(
    Guid Id, string Name, DateOnly StartDate, DateOnly? EndDate, string Description, IReadOnlyList<DocumentRef> Documents);

/// <summary>
/// A document of a project. <see cref="Url"/> is <c>&lt;endpoint&gt;/&lt;tid&gt;/&lt;projectId&gt;/&lt;documentId&gt;</c>
/// without a query; its last segment is the document ID.
/// </summary>
public sealed record DocumentRef(string Url, string Name, long Size, string ContentType);

/// <summary>Where to PUT the file: <see cref="BlobUrl"/> carries the signed query and is used as is.</summary>
public sealed record UploadUrlResponse(string BlobUrl, DateTimeOffset Expires);

/// <summary>The tenant already has this file (same SHA-256, name and size): no upload, add this reference instead.</summary>
public sealed record DuplicateDocumentResponse(DocumentRef Document);
