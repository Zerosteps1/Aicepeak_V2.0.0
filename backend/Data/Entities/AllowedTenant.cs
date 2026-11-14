namespace Aicepeak.Api.Data.Entities;

/// <summary>A Microsoft Entra tenant whose users and apps may sign in.</summary>
public sealed class AllowedTenant {
    /// <summary>Tenant ID (<c>tid</c>).</summary>
    public required Guid Tid { get; set; }
}
