namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>The failure messages of the API's claim checks after a token passed signature, audience, issuer and lifetime.</summary>
public static class Rejections {
    public const string NotV2 = "The token is not a v2.0 token.";
    public const string NotSingleAudience = "The token must have exactly one audience.";
    public const string NoTidOrOid = "The token has no valid tid or oid.";
    public const string NoNbf = "The token has no nbf.";
    public const string PersonalAccount = "Personal Microsoft accounts are not allowed.";
    public const string ClientNotAllowed = "The token was not issued to an allowed client.";
    public const string MissingScope = "The user token lacks the required scope.";
    public const string NotAnAppToken = "The app token lacks the required role or idtyp=app.";
    public const string TenantNotAllowed = "The tenant is not allowed.";

    /// <summary>The database could not be asked; a token that gets this far passed every token check.</summary>
    public const string AllowlistUnavailable = "The tenant allowlist could not be checked.";
}
