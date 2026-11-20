namespace Aicepeak.Api.Data.Entities;

/// <summary>A forecast project of a tenant, stored in the tenant's own database (<see cref="TenantDbContext"/>).</summary>
public sealed class Project {
    public const int MaxNameLength = 200;
    public const int MaxDescriptionLength = 4000;

    /// <summary>A version 7 GUID, assigned on creation and never changed.</summary>
    public required Guid Id { get; init; }

    /// <summary>Trimmed; unique within the tenant, ignoring case.</summary>
    public required string Name { get; set; }

    public required DateOnly StartDate { get; set; }

    /// <summary>Not before <see cref="StartDate"/>; <c>null</c> means open-ended.</summary>
    public DateOnly? EndDate { get; set; }

    public required string Description { get; set; }
}
