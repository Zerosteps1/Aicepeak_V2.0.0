namespace Aicepeak.Api.Data.Entities;

/// <summary>A person who signed in with Microsoft Entra ID, identified by tenant ID and object ID.</summary>
public sealed class User {
    /// <summary>Tenant ID (<c>tid</c>) of the user's Microsoft Entra tenant.</summary>
    public required Guid Tid { get; set; }

    /// <summary>Object ID (<c>oid</c>) of the user in that tenant.</summary>
    public required Guid Oid { get; set; }

    public required string Name { get; set; }
}
