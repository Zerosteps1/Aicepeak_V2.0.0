namespace Aicepeak.Api.Data.Entities;

public sealed class User
{
    /// <summary>Identifier of the user in Microsoft Entra ID.</summary>
    public required string EntraId { get; set; }

    public required string Name { get; set; }
}
