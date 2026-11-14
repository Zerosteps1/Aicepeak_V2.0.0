using System.Net.Http.Headers;
using Microsoft.AspNetCore.Authentication;

namespace Aicepeak.Api.Tests.Infrastructure;

public static class BearerRequests {
    public const string LoginPath = "/api/v1/login";
    public const string ProtectedPath = "/" + ProtectedTestController.Path;

    /// <summary>Sends a request with <c>Authorization: Bearer {token}</c>, or without the header if the token is null.</summary>
    public static Task<HttpResponseMessage> SendAsync(this HttpClient client, HttpMethod method, string path, string? token) {
        var request = new HttpRequestMessage(method, path);
        if (token is not null) {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return client.SendAsync(request, TestContext.Current.CancellationToken);
    }

    /// <summary>
    /// The reason recorded for the only rejected token: the message of a failed claim check, otherwise the type name of
    /// the token validation exception.
    /// </summary>
    public static string SingleRejection(this ApiFactory factory) {
        var failure = Assert.Single(factory.AuthenticationFailures);
        return failure is AuthenticationFailureException ? failure.Message : failure.GetType().Name;
    }
}
