using System.Security.Claims;
using Aicepeak.Api.Data;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Microsoft.IdentityModel.Validators;

namespace Aicepeak.Api.Auth;

/// <summary>
/// Validates Microsoft Entra ID v2 access tokens (JWT bearer) of users and apps. Every check is explicit; a token that
/// fails one is rejected with 401. Missing or invalid <see cref="EntraOptions"/> reject every token but never stop the app.
/// </summary>
public static class EntraAuthentication {
    public const string MissingHeaderMessage = "Authentication header missing";

    /// <summary>Category of the rejection log; outside <c>Microsoft.AspNetCore</c>, whose Information logs are filtered out.</summary>
    public const string LogCategory = "Aicepeak.Api.Auth";

    private const string ScopeClaim = "scp";

    /// <summary>The tenant of personal Microsoft accounts; never allowed.</summary>
    private static readonly Guid PersonalAccountsTenant = new("9188040d-6c67-4c5b-b112-36a304b66dad");

    public static IServiceCollection AddEntraAuthentication(this IServiceCollection services, IConfiguration configuration) {
        services.AddOptions<EntraOptions>().Bind(configuration);
        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();
        services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
            .Configure<IOptions<EntraOptions>>((options, entra) => Configure(options, entra.Value));
        services.AddAuthorization();

        return services;
    }

    /// <summary>
    /// True for a user (delegated) token, false for an app token. Only meaningful for a principal authenticated here,
    /// where a token with <c>scp</c> passed the scope check and a token without it passed the app role check.
    /// </summary>
    public static bool IsUserToken(ClaimsPrincipal principal) => principal.HasClaim(claim => claim.Type == ScopeClaim);

    private static void Configure(JwtBearerOptions options, EntraOptions entra) {
        // Without a valid https address there is no metadata and no signing key, so every token is rejected.
        if (entra.ValidMetadataAddress is { } metadataAddress) {
            options.MetadataAddress = metadataAddress;
        }

        options.MapInboundClaims = false;
        options.IncludeErrorDetails = false;
        options.TokenValidationParameters = new TokenValidationParameters {
            ValidAlgorithms = [SecurityAlgorithms.RsaSha256],
            ValidateIssuerSigningKey = true,
            // No audience configured: audience validation fails for every token.
            ValidAudience = string.IsNullOrWhiteSpace(entra.Audience) ? null : entra.Audience.Trim(),
            // Exact match only: no "<audience>/" variant (CheckClaims also requires a single aud).
            IgnoreTrailingSlashWhenValidatingAudience = false,
            IssuerValidator = ValidateIssuer,
            ValidateLifetime = true,
            RequireExpirationTime = true,
            ClockSkew = TimeSpan.FromMinutes(5),
        };
        // The organizations keys serve every tenant; a key that Entra binds to an issuer must match the token's tid.
        options.TokenValidationParameters.EnableAadSigningKeyIssuerValidation();
        options.Events = new JwtBearerEvents {
            OnAuthenticationFailed = LogFailedValidation,
            OnTokenValidated = context => ValidateTokenAsync(context, entra),
            OnChallenge = ChallengeAsync,
        };
    }

    /// <summary>The issuer must be the v2 issuer of the token's own tenant.</summary>
    private static string ValidateIssuer(string issuer, SecurityToken token, TokenValidationParameters parameters) {
        if (token is JsonWebToken jwt
            && jwt.TryGetPayloadValue<string>("tid", out var tid)
            && !string.IsNullOrEmpty(tid)
            && string.Equals(issuer, $"https://login.microsoftonline.com/{tid}/v2.0", StringComparison.Ordinal)) {
            return issuer;
        }

        throw new SecurityTokenInvalidIssuerException("The issuer is not the v2 issuer of the token's tenant.") {
            InvalidIssuer = issuer,
        };
    }

    /// <summary>Signature, lifetime, issuer or audience failed: logs the kind of failure, never the token.</summary>
    private static Task LogFailedValidation(AuthenticationFailedContext context) {
        Logger(context.HttpContext).LogWarning(
            "Bearer token rejected on {Path}: {Failure}.", context.Request.Path, context.Exception.GetType().Name);
        return Task.CompletedTask;
    }

    /// <summary>Runs after signature, audience, issuer and lifetime passed.</summary>
    private static async Task ValidateTokenAsync(TokenValidatedContext context, EntraOptions entra) {
        var failure = CheckClaims(context.Principal!, entra, out var tid);
        if (failure is not null) {
            Reject(context, failure);
            return;
        }

        try {
            var db = context.HttpContext.RequestServices.GetRequiredService<AppDbContext>();
            if (!await db.AllowedTenants.AnyAsync(tenant => tenant.Tid == tid, context.HttpContext.RequestAborted)) {
                Reject(context, "The tenant is not allowed.");
            }
        } catch (Exception exception) {
            Reject(context, "The tenant allowlist could not be checked.", exception);
        }
    }

    /// <summary>
    /// Fails a token that passed signature, lifetime, issuer and audience, and logs why with its (signed) tid and azp,
    /// never the token or the user's name.
    /// </summary>
    private static void Reject(TokenValidatedContext context, string reason, Exception? exception = null) {
        Logger(context.HttpContext).LogWarning(
            exception,
            "Bearer token rejected on {Path}: {Reason} (tid {Tid}, azp {Azp}).",
            context.Request.Path,
            reason,
            context.Principal?.FindFirstValue("tid"),
            context.Principal?.FindFirstValue("azp"));
        context.Fail(reason);
    }

    private static ILogger Logger(HttpContext context) =>
        context.RequestServices.GetRequiredService<ILoggerFactory>().CreateLogger(LogCategory);

    private static string? CheckClaims(ClaimsPrincipal principal, EntraOptions entra, out Guid tid) {
        tid = Guid.Empty;
        if (SingleValue(principal, "ver") != "2.0") {
            return "The token is not a v2.0 token.";
        }

        // Entra v2 access tokens carry exactly one aud; the audience validation only checked that ours is among them.
        if (SingleValue(principal, "aud") is null) {
            return "The token must have exactly one audience.";
        }

        if (!TryParseGuid(SingleValue(principal, "tid"), out tid) || !TryParseGuid(SingleValue(principal, "oid"), out _)) {
            return "The token has no valid tid or oid.";
        }

        if (SingleValue(principal, "nbf") is null) {
            return "The token has no nbf.";
        }

        if (tid == PersonalAccountsTenant) {
            return "Personal Microsoft accounts are not allowed.";
        }

        // A personal account invited as a guest signs in through a work tenant; idp still names the Microsoft account.
        if (SingleValue(principal, "idp") is { } idp && IsPersonalAccountProvider(idp)) {
            return "Personal Microsoft accounts are not allowed as guests.";
        }

        var azp = SingleValue(principal, "azp");
        if (azp is null || !entra.AllowedClientIds.Contains(azp)) {
            return "The token was not issued to an allowed client.";
        }

        if (IsUserToken(principal)) {
            var scopes = SingleValue(principal, ScopeClaim)?.Split(' ', StringSplitOptions.RemoveEmptyEntries) ?? [];
            var hasScope = !string.IsNullOrWhiteSpace(entra.Scope) && scopes.Contains(entra.Scope.Trim(), StringComparer.Ordinal);
            return hasScope ? null : "The user token lacks the required scope.";
        }

        var isApp = !string.IsNullOrWhiteSpace(entra.AppRole)
            && principal.FindAll("roles").Any(role => string.Equals(role.Value, entra.AppRole.Trim(), StringComparison.Ordinal))
            && SingleValue(principal, "idtyp") == "app";
        return isApp ? null : "The app token lacks the required role or idtyp=app.";
    }

    /// <summary>The value of a claim that occurs exactly once, otherwise <c>null</c>.</summary>
    private static string? SingleValue(ClaimsPrincipal principal, string type) {
        var claims = principal.FindAll(type).Take(2).ToList();
        return claims.Count == 1 ? claims[0].Value : null;
    }

    private static bool TryParseGuid(string? value, out Guid guid) => Guid.TryParseExact(value, "D", out guid);

    /// <summary><c>live.com</c> or an STS URI of the personal accounts tenant (Entra access token claims reference).</summary>
    private static bool IsPersonalAccountProvider(string idp) =>
        string.Equals(idp, "live.com", StringComparison.OrdinalIgnoreCase)
        || idp.Contains(PersonalAccountsTenant.ToString(), StringComparison.OrdinalIgnoreCase);

    /// <summary>Without an Authorization header: 401 with a short text. Otherwise the default bearer challenge.</summary>
    private static Task ChallengeAsync(JwtBearerChallengeContext context) {
        if (context.Request.Headers.Authorization.Count > 0) {
            return Task.CompletedTask;
        }

        context.HandleResponse();
        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        context.Response.Headers.WWWAuthenticate = JwtBearerDefaults.AuthenticationScheme;
        context.Response.ContentType = "text/plain; charset=utf-8";
        return context.Response.WriteAsync(MissingHeaderMessage, context.HttpContext.RequestAborted);
    }
}
