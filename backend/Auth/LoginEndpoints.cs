using System.Security.Claims;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Aicepeak.Api.Auth;

public static class LoginEndpoints {
    /// <summary>The stored user record.</summary>
    public sealed record UserResponse(Guid Tid, Guid Oid, string Name);

    /// <summary>
    /// <c>PUT /login</c>: called once after each sign-in. Creates the user record of the signed-in user if it does not exist
    /// yet and returns it; an existing record is returned unchanged. App tokens get 401 and never a record.
    /// </summary>
    public static RouteGroupBuilder MapLogin(this RouteGroupBuilder group) {
        group.MapPut("/login", LoginAsync);

        return group;
    }

    private static async Task<Results<Ok<UserResponse>, UnauthorizedHttpResult>> LoginAsync(
        ClaimsPrincipal principal, AppDbContext db, CancellationToken cancellationToken) {
        if (!EntraAuthentication.IsUserToken(principal)
            || !Guid.TryParse(principal.FindFirstValue("tid"), out var tid)
            || !Guid.TryParse(principal.FindFirstValue("oid"), out var oid)) {
            return TypedResults.Unauthorized();
        }

        var user = await db.Users.AsNoTracking().SingleOrDefaultAsync(u => u.Tid == tid && u.Oid == oid, cancellationToken);
        if (user is null) {
            user = new User {
                Tid = tid,
                Oid = oid,
                Name = principal.FindFirstValue("name") ?? principal.FindFirstValue("preferred_username") ?? "",
            };
            db.Users.Add(user);
            try {
                await db.SaveChangesAsync(cancellationToken);
            } catch (DbUpdateException exception) when (exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation }) {
                // A concurrent sign-in of the same user created the record first.
                db.Entry(user).State = EntityState.Detached;
                user = await db.Users.AsNoTracking().SingleAsync(u => u.Tid == tid && u.Oid == oid, cancellationToken);
            }
        }

        return TypedResults.Ok(new UserResponse(user.Tid, user.Oid, user.Name));
    }
}
