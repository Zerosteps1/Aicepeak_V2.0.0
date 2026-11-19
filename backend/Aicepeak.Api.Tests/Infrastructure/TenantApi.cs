using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Azure.Storage.Blobs;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// The API for one fresh tenant: a new tid in <c>allowed_tenants</c> of a migrated main database, the API hosted with
/// that database (and Azurite, if given; otherwise the offline development storage), and a client whose requests carry
/// a user token of that tenant. Analysis mocks run without delays.
/// </summary>
public sealed class TenantApi : IAsyncDisposable {
    public const string Base = "/api/v1/project";

    private static readonly HttpClient Storage = new();

    private readonly PostgresFixture _postgres;
    private readonly AzuriteFixture? _azurite;

    private TenantApi(PostgresFixture postgres, AzuriteFixture? azurite, Guid tid, ApiFactory factory) {
        _postgres = postgres;
        _azurite = azurite;
        Tid = tid;
        Factory = factory;
        Client = factory.CreateClient();
        Client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", TestTokens.User(tid).Build());
    }

    public Guid Tid { get; }

    public ApiFactory Factory { get; }

    /// <summary>Sends a user token of <see cref="Tid"/> with every request.</summary>
    public HttpClient Client { get; }

    /// <summary>The tenant's blob container in Azurite.</summary>
    public BlobContainerClient Container =>
        new BlobServiceClient(_azurite?.ConnectionString ?? throw new InvalidOperationException("No Azurite."))
            .GetBlobContainerClient(Tid.ToString());

    public static async Task<TenantApi> CreateAsync(
        PostgresFixture postgres,
        AzuriteFixture? azurite = null,
        Action<IServiceCollection>? configureServices = null,
        string mainDatabase = "tenant_api") {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await using (var db = new AppDbContext(new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(postgres.ConnectionString(mainDatabase)).Options)) {
            await db.Database.MigrateAsync(ct);
            db.AllowedTenants.Add(new AllowedTenant { Tid = tid });
            await db.SaveChangesAsync(ct);
        }

        var settings = TestSettings.WithEntra(postgres.Settings(database: mainDatabase));
        settings["MOCK_PROCESSING_STEP_MS"] = "0";
        if (azurite is not null) {
            settings["BLOB_CON_STR"] = azurite.ConnectionString;
        }

        return new TenantApi(postgres, azurite, tid, new ApiFactory(TestSettings.Production, settings, configureServices: configureServices));
    }

    public ValueTask DisposeAsync() {
        Client.Dispose();
        return Factory.DisposeAsync();
    }

    /// <summary>A context on the tenant's database (exists after the tenant's first project request).</summary>
    public TenantDbContext CreateDb() =>
        new(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql(_postgres.ConnectionString(Tid.ToString())).Options);

    public Task<HttpResponseMessage> SendJsonAsync(HttpMethod method, string path, object body) =>
        SendRawAsync(method, path, JsonSerializer.Serialize(body, JsonSerializerOptions.Web));

    public Task<HttpResponseMessage> SendRawAsync(HttpMethod method, string path, string json, string mediaType = "application/json") =>
        Client.SendAsync(
            new HttpRequestMessage(method, path) { Content = new StringContent(json, Encoding.UTF8, mediaType) },
            TestContext.Current.CancellationToken);

    /// <summary>Creates a project; fails the test unless the API answers 201.</summary>
    public async Task<Guid> CreateProjectAsync(string? name = null, string startDate = "2026-01-01") {
        var response = await SendJsonAsync(HttpMethod.Post, Base, new { name = name ?? $"Projekt {Guid.NewGuid():N}", startDate });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await ReadJsonAsync(response)).GetProperty("id").GetGuid();
    }

    public async Task<JsonElement> GetProjectAsync(Guid projectId) {
        var response = await Client.GetAsync($"{Base}/{projectId}", TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await ReadJsonAsync(response);
    }

    public Task<HttpResponseMessage> RequestUploadUrlAsync(Guid projectId, byte[] content, string name, string contentType = "application/pdf") =>
        SendJsonAsync(HttpMethod.Post, $"{Base}/{projectId}/upload-url", new {
            sha256 = Convert.ToHexStringLower(SHA256.HashData(content)),
            name,
            size = content.Length,
            contentType,
        });

    /// <summary>Gets an upload URL and PUTs the file like the browser; returns the signed URL.</summary>
    public async Task<string> UploadAsync(Guid projectId, byte[] content, string name, string contentType = "application/pdf") {
        var response = await RequestUploadUrlAsync(projectId, content, name, contentType);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var blobUrl = (await ReadJsonAsync(response)).GetProperty("blobUrl").GetString()!;
        var put = await PutBlobAsync(blobUrl, content, contentType);
        Assert.Equal(HttpStatusCode.Created, put.StatusCode);
        return blobUrl;
    }

    /// <summary>Uploads a file and adds it with a PATCH; returns the document reference from the response.</summary>
    public async Task<DocumentRefBody> AddDocumentAsync(Guid projectId, byte[] content, string name, string contentType = "application/pdf") {
        var blobUrl = await UploadAsync(projectId, content, name, contentType);
        var reference = new DocumentRefBody(WithoutQuery(blobUrl), name, content.Length, contentType);
        var response = await PatchDocumentsAsync(projectId, reference);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return reference;
    }

    public Task<HttpResponseMessage> PatchDocumentsAsync(Guid projectId, params DocumentRefBody[] documents) =>
        SendJsonAsync(HttpMethod.Patch, $"{Base}/{projectId}", new { documents });

    /// <summary>A PUT as the browser sends it to an Azure upload URL: no Authorization header.</summary>
    public static Task<HttpResponseMessage> PutBlobAsync(string blobUrl, byte[] content, string contentType) {
        var request = new HttpRequestMessage(HttpMethod.Put, blobUrl) { Content = new ByteArrayContent(content) };
        request.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(contentType);
        request.Headers.Add("x-ms-blob-type", "BlockBlob");
        return Storage.SendAsync(request, TestContext.Current.CancellationToken);
    }

    public static string WithoutQuery(string url) => url.Split('?')[0];

    public static string DocumentId(string url) => WithoutQuery(url).Split('/')[^1];

    public static async Task<JsonElement> ReadJsonAsync(HttpResponseMessage response) =>
        (await response.Content.ReadFromJsonAsync<JsonElement>(TestContext.Current.CancellationToken));

    /// <summary>The failure reasons per field of a 400 ValidationProblem.</summary>
    public static async Task<Dictionary<string, string[]>> ReadErrorsAsync(HttpResponseMessage response) {
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        var problem = await ReadJsonAsync(response);
        return problem.GetProperty("errors").Deserialize<Dictionary<string, string[]>>()!;
    }

    /// <summary>A PDF-like test file of <paramref name="size"/> bytes; the content depends on <paramref name="marker"/>.</summary>
    public static byte[] File(string marker, int size = 2048) {
        var content = new byte[size];
        var text = Encoding.UTF8.GetBytes($"%PDF-1.7 {marker} ");
        for (var index = 0; index < size; index++) {
            content[index] = text[index % text.Length];
        }

        return content;
    }
}

/// <summary>A <c>DocumentRef</c> as the client sends it.</summary>
public sealed record DocumentRefBody(string Url, string Name, long Size, string ContentType);
