using Aicepeak.Api.Auth;

namespace Aicepeak.Api.Data;

/// <summary>
/// Guards the endpoints of tenant data: only user tokens with a tenant ID pass (app tokens get 401, as for
/// <c>/login</c>), and the tenant's database is created and migrated before the handler runs.
/// </summary>
public sealed class TenantEndpointFilter(TenantDatabaseMigrator migrator) : IEndpointFilter {
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next) {
        var principal = context.HttpContext.User;
        if (!EntraAuthentication.IsUserToken(principal) || !EntraAuthentication.TryGetTenantId(principal, out var tid)) {
            return TypedResults.Unauthorized();
        }

        await migrator.EnsureMigratedAsync(tid, context.HttpContext.RequestAborted);
        return await next(context);
    }
}
