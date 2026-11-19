namespace Aicepeak.Api.Data.Entities;

/// <summary>Links a <see cref="Document"/> to a <see cref="Project"/> (many-to-many).</summary>
public sealed class ProjectDocument {
    public required Guid ProjectId { get; init; }

    public required Guid DocumentId { get; init; }
}
