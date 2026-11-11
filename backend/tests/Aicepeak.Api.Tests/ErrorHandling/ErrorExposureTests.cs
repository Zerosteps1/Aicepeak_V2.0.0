using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.ErrorHandling;

/// <summary>AC-5: in Production no endpoint exposes exception details.</summary>
public sealed class ErrorExposureTests
{
    private const string ThrowingEndpoint = "/api/v1/test/throw";

    [Fact]
    public async Task Production_UnhandledException_ReturnsProblemDetailsWithoutDetails()
    {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.UnreachableDatabase());

        var response = await factory.CreateClient().GetAsync(ThrowingEndpoint, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        var body = await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken);
        Assert.DoesNotContain(ThrowingTestController.Marker, body);
        Assert.DoesNotContain(nameof(InvalidOperationException), body);
        Assert.DoesNotContain("   at ", body);
    }

    [Fact]
    public async Task Development_UnhandledException_ShowsDetails()
    {
        await using var factory = new ApiFactory(TestSettings.Development, TestSettings.UnreachableDatabase());

        var response = await factory.CreateClient().GetAsync(ThrowingEndpoint, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains(ThrowingTestController.Marker, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Production_OpenApiDocument_IsNotExposed()
    {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.UnreachableDatabase());

        var response = await factory.CreateClient().GetAsync("/openapi/v1.json", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
