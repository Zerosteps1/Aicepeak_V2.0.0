using Microsoft.AspNetCore.Mvc;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// Test-only endpoint protected like every controller (<c>MapControllers().RequireAuthorization()</c>): 200 for any
/// authenticated user or app token.
/// </summary>
[ApiController]
[Route(Path)]
public sealed class ProtectedTestController : ControllerBase {
    public const string Path = "api/v1/test/protected";

    [HttpGet]
    public IActionResult Get() => Ok();
}
