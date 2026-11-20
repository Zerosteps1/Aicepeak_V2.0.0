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

/// <summary>Documentation only (OpenAPI): the body of <c>POST /project</c>, parsed by <see cref="ProjectInput"/>.</summary>
public sealed record CreateProjectRequest(string Name, DateOnly StartDate, DateOnly? EndDate = null, string Description = "");

/// <summary>
/// Documentation only (OpenAPI): the body of <c>PATCH /project/{id}</c>, parsed by <see cref="ProjectInput"/>. Every
/// property is optional and a missing one stays unchanged; only <see cref="EndDate"/> may be <c>null</c> (clears it).
/// </summary>
public sealed record UpdateProjectRequest {
    /// <summary>If given, it must be the project's ID.</summary>
    public Guid Id { get; init; }

    public string Name { get; init; } = "";

    public DateOnly StartDate { get; init; }

    public DateOnly? EndDate { get; init; }

    public string Description { get; init; } = "";

    /// <summary>Documents to add; links are never removed here.</summary>
    public IReadOnlyList<DocumentRef> Documents { get; init; } = [];
}

/// <summary>Documentation only (OpenAPI): the body of <c>POST /project/{id}/upload-url</c>, parsed by <see cref="UploadUrlInput"/>.</summary>
public sealed record UploadUrlRequest(string Sha256, string Name, long Size, string ContentType);
