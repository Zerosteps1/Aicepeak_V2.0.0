using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>Test-only endpoint that fails with a recognisable message. Anonymous, unlike the API's controllers.</summary>
[ApiController]
[AllowAnonymous]
[Route("api/v1/test/throw")]
public sealed class ThrowingTestController : ControllerBase {
    public const string Marker = "boom-marker-91c2";

    [HttpGet]
    public IActionResult Get() => throw new InvalidOperationException(Marker);
}
