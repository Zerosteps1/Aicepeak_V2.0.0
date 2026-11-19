namespace Aicepeak.Api.Data.Entities;

/// <summary>
/// An uploaded file of a tenant. Documents never change (init-only here, a trigger in the database) and can be linked
/// to several projects (<see cref="ProjectDocument"/>); a document knows no project type.
/// </summary>
public sealed class Document {
    public const int MaxNameLength = 200;
    public const int MaxContentTypeLength = 255;
    public const int Sha256Length = 32;

    /// <summary>The document ID; the last segment of its blob name and URL.</summary>
    public required Guid Id { get; init; }

    /// <summary>The project the file was uploaded to; its ID is the first segment of <see cref="BlobName"/>.</summary>
    public required Guid ProjectId { get; init; }

    /// <summary>The blob name in the tenant's storage space, <c>&lt;projectId&gt;/&lt;documentId&gt;</c>.</summary>
    public required string BlobName { get; init; }

    /// <summary>The file name, e.g. <c>Jahresabschluss 2025.pdf</c>.</summary>
    public required string Name { get; init; }

    /// <summary>Size in bytes.</summary>
    public required long Size { get; init; }

    public required string ContentType { get; init; }

    /// <summary>SHA-256 of the content, computed by the backend.</summary>
    public required byte[] Sha256 { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }
}
