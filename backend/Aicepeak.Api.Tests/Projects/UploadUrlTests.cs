using System.Net;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Tests.Infrastructure;
using Azure.Storage.Blobs.Models;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// <c>POST /project/{id}/upload-url</c> against PostgreSQL and Azurite (Docker): AC-1 (a signed URL to create one blob
/// in the tenant's private container, valid 15 minutes), AC-2, AC-17 (an expired URL is refused), AC-19 (declared size)
/// and the duplicate lookup.
/// </summary>
[Collection(StorageCollection.Name)]
[Trait("Category", "Database")]
public sealed class UploadUrlTests(PostgresFixture postgres, AzuriteFixture azurite) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task AC01_UploadUrl_CreatesOneBlobInTheTenantsPrivateContainer_For15Minutes() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var before = DateTimeOffset.UtcNow;

        var response = await api.RequestUploadUrlAsync(projectId, TenantApi.File("a"), "Bilanz.pdf");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await TenantApi.ReadJsonAsync(response);
        Assert.Equal(["blobUrl", "expires"], body.EnumerateObject().Select(property => property.Name));
        var url = new Uri(body.GetProperty("blobUrl").GetString()!);
        var expires = body.GetProperty("expires").GetDateTimeOffset();
        var segments = url.AbsolutePath.Split('/');
        Assert.Equal([api.Tid.ToString(), projectId.ToString()], segments[^3..^1]);
        Assert.Equal(7, Guid.Parse(segments[^1]).Version);
        var query = QueryHelpers.ParseQuery(url.Query);
        Assert.Equal("b", query["sr"]);
        Assert.Equal("c", query["sp"]);
        Assert.False(query.ContainsKey("st"));
        Assert.Equal(expires, DateTimeOffset.Parse(query["se"]!));
        Assert.InRange(expires - before, TimeSpan.FromMinutes(15) - TimeSpan.FromSeconds(5), TimeSpan.FromMinutes(15) + TimeSpan.FromSeconds(1));
        var access = await api.Container.GetAccessPolicyAsync(cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(PublicAccessType.None, access.Value.BlobPublicAccess);
    }

    [Fact]
    public async Task AC01_PutToTheUrl_Returns201_AndStoresTheFile_ButTheUrlCannotReadOrOverwrite() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("b");

        var blobUrl = await api.UploadAsync(projectId, content, "Bilanz.pdf");

        var blob = api.Container.GetBlobClient(string.Join('/', new Uri(blobUrl).AbsolutePath.Split('/')[^2..]));
        var stored = (await blob.DownloadContentAsync(TestContext.Current.CancellationToken)).Value;
        Assert.Equal(content, stored.Content.ToArray());
        Assert.Equal("application/pdf", stored.Details.ContentType);
        var read = await new HttpClient().GetAsync(blobUrl, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.Forbidden, read.StatusCode);
        var overwrite = await TenantApi.PutBlobAsync(blobUrl, TenantApi.File("other"), "application/pdf");
        // Create (sp=c) does not include overwriting an existing blob.
        Assert.Equal(HttpStatusCode.Forbidden, overwrite.StatusCode);
        Assert.Equal(content, (await blob.DownloadContentAsync(TestContext.Current.CancellationToken)).Value.Content.ToArray());
    }

    [Fact]
    public async Task AC02_UnknownProject_Returns404_AndIssuesNoUrl() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        await api.CreateProjectAsync();

        var response = await api.RequestUploadUrlAsync(Guid.CreateVersion7(), TenantApi.File("c"), "Bilanz.pdf");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.False(await api.Container.ExistsAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC17_ExpiredUrl_IsRefusedByTheStorage() {
        // The blob-sas clock runs 16 minutes behind, so the URL is already expired when it is issued.
        var clock = new ShiftedTimeProvider(TimeSpan.FromMinutes(-16));
        await using var api = await TenantApi.CreateAsync(
            postgres, azurite, services => services.AddKeyedSingleton<TimeProvider>(DocumentBlobs.TimeProviderKey, clock));
        var projectId = await api.CreateProjectAsync();

        var response = await api.RequestUploadUrlAsync(projectId, TenantApi.File("d"), "Bilanz.pdf");
        var body = await TenantApi.ReadJsonAsync(response);
        var put = await TenantApi.PutBlobAsync(body.GetProperty("blobUrl").GetString()!, TenantApi.File("d"), "application/pdf");

        Assert.True(body.GetProperty("expires").GetDateTimeOffset() < DateTimeOffset.UtcNow);
        Assert.Equal(HttpStatusCode.Forbidden, put.StatusCode);
        Assert.Empty(await BlobNamesAsync(api));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(52_428_801)]
    public async Task AC19_DeclaredSizeOutside1To50MB_Returns400_WithoutUrl(long size) {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();

        var response = await api.SendJsonAsync(HttpMethod.Post, $"{Base}/{projectId}/upload-url", new {
            sha256 = new string('a', 64),
            name = "Bilanz.pdf",
            size,
            contentType = "application/pdf",
        });

        Assert.Equal(["must be an integer from 1 to 52428800"], (await TenantApi.ReadErrorsAsync(response))["size"]);
    }

    [Fact]
    public async Task AC19_DeclaredSizeOfExactly50MB_GetsAUrl() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();

        var response = await api.SendJsonAsync(HttpMethod.Post, $"{Base}/{projectId}/upload-url", new {
            sha256 = new string('A', 64),
            name = "Groß.XLSX",
            size = 52_428_800,
            contentType = "application/octet-stream",
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task AC05_InvalidBody_ListsEveryFailure() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();

        var response = await api.SendRawAsync(HttpMethod.Post, $"{Base}/{projectId}/upload-url", """
            {"sha256":"xyz","name":"../Bilanz.exe","size":"12","extra":true}
            """);

        Assert.Equal(
            new Dictionary<string, string[]> {
                ["sha256"] = ["must be a SHA-256 hash of 64 hex digits"],
                ["name"] = ["must be a file name of at most 200 characters ending in .pdf, .doc, .docx, .xls or .xlsx"],
                ["size"] = ["must be an integer from 1 to 52428800"],
                ["extra"] = ["is not a known property"],
                ["contentType"] = ["is required"],
            },
            await TenantApi.ReadErrorsAsync(response));
    }

    [Theory]
    [InlineData("Bilanz.pdf", true)]
    [InlineData("Umsatz 2025.Xlsx", true)]
    [InlineData("a.doc", true)]
    [InlineData("a.docx", true)]
    [InlineData("a.xls", true)]
    [InlineData(".pdf", false)]
    [InlineData("Bilanz.pdf.exe", false)]
    [InlineData("Bilanz", false)]
    [InlineData("ordner/Bilanz.pdf", false)]
    [InlineData("ordner\\Bilanz.pdf", false)]
    [InlineData("Bil\tanz.pdf", false)]
    public async Task AC05_DocumentName_MustBeAFileNameWithAnAllowedExtension(string name, bool valid) {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();

        var response = await api.RequestUploadUrlAsync(projectId, TenantApi.File("e"), name);

        Assert.Equal(valid ? HttpStatusCode.OK : HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task AC05_DocumentNameLongerThan200Characters_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();

        var longest = await api.RequestUploadUrlAsync(projectId, TenantApi.File("f"), new string('n', 196) + ".pdf");
        var tooLong = await api.RequestUploadUrlAsync(projectId, TenantApi.File("f"), new string('n', 197) + ".pdf");

        Assert.Equal(HttpStatusCode.OK, longest.StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, tooLong.StatusCode);
    }

    [Fact]
    public async Task Duplicate_SameHashNameAndSizeInTheTenant_ReturnsTheStoredDocumentInsteadOfAUrl() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var first = await api.CreateProjectAsync();
        var second = await api.CreateProjectAsync();
        var content = TenantApi.File("g");
        var stored = await api.AddDocumentAsync(first, content, "Bilanz.pdf");

        var duplicate = await api.RequestUploadUrlAsync(second, content, "Bilanz.pdf");
        var otherName = await api.RequestUploadUrlAsync(second, content, "Bilanz Kopie.pdf");
        var otherContent = await api.RequestUploadUrlAsync(second, TenantApi.File("h"), "Bilanz.pdf");

        var body = await TenantApi.ReadJsonAsync(duplicate);
        Assert.Equal(["document"], body.EnumerateObject().Select(property => property.Name));
        var document = body.GetProperty("document");
        Assert.Equal(stored.Url, document.GetProperty("url").GetString());
        Assert.Equal("Bilanz.pdf", document.GetProperty("name").GetString());
        Assert.Equal(content.Length, document.GetProperty("size").GetInt64());
        Assert.Equal("application/pdf", document.GetProperty("contentType").GetString());
        Assert.True((await TenantApi.ReadJsonAsync(otherName)).TryGetProperty("blobUrl", out _));
        Assert.True((await TenantApi.ReadJsonAsync(otherContent)).TryGetProperty("blobUrl", out _));
    }

    [Fact]
    public async Task Duplicate_OfAnotherTenant_IsNotFound() {
        await using var owner = await TenantApi.CreateAsync(postgres, azurite);
        await using var other = await TenantApi.CreateAsync(postgres, azurite);
        var content = TenantApi.File("i");
        await owner.AddDocumentAsync(await owner.CreateProjectAsync(), content, "Bilanz.pdf");

        var response = await other.RequestUploadUrlAsync(await other.CreateProjectAsync(), content, "Bilanz.pdf");

        Assert.True((await TenantApi.ReadJsonAsync(response)).TryGetProperty("blobUrl", out _));
    }

    private static async Task<List<string>> BlobNamesAsync(TenantApi api) {
        var names = new List<string>();
        if (!await api.Container.ExistsAsync(TestContext.Current.CancellationToken)) {
            return names;
        }

        await foreach (var blob in api.Container.GetBlobsAsync(new GetBlobsOptions(), TestContext.Current.CancellationToken)) {
            names.Add(blob.Name);
        }

        return names;
    }
}
