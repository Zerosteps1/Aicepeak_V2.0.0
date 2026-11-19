using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using Aicepeak.Api.Tests.Infrastructure;
using Azure.Storage.Blobs.Models;
using Azure.Storage.Blobs.Specialized;
using Microsoft.EntityFrameworkCore;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// <c>documents</c> in <c>PATCH /project/{id}</c> against PostgreSQL and Azurite (Docker): AC-4 (adds, idempotent, never
/// removes), AC-15 (only this tenant's uploads of this project without query, with an existing blob), metadata checks
/// listing every failure, AC-19 (an oversized blob is deleted, an empty one refused), duplicates (and a replayed PATCH
/// of a replaced upload), collisions and cross-project links.
/// </summary>
[Collection(StorageCollection.Name)]
[Trait("Category", "Database")]
public sealed class DocumentPatchTests(PostgresFixture postgres, AzuriteFixture azurite) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task AC04_Patch_AddsTheUploadedDocument_WithTheHashComputedByTheBackend() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("a", 300_000);
        var blobUrl = await api.UploadAsync(projectId, content, "Jahresabschluss 2025.pdf");
        var reference = new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Jahresabschluss 2025.pdf", content.Length, "application/pdf");

        var response = await api.PatchDocumentsAsync(projectId, reference);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal([reference], Documents(await TenantApi.ReadJsonAsync(response)));
        await using var db = api.CreateDb();
        var document = await db.Documents.SingleAsync(TestContext.Current.CancellationToken);
        Assert.Equal(Guid.Parse(TenantApi.DocumentId(blobUrl)), document.Id);
        Assert.Equal(projectId, document.ProjectId);
        Assert.Equal(SHA256.HashData(content), document.Sha256);
        Assert.Equal($"{projectId}/{document.Id}", document.BlobName);
        Assert.True(await db.ProjectDocuments.AnyAsync(link => link.ProjectId == projectId && link.DocumentId == document.Id, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC04_Patch_IsIdempotent_AndNeverRemovesDocuments() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var first = await api.AddDocumentAsync(projectId, TenantApi.File("b1"), "Bilanz.pdf");
        var second = await api.AddDocumentAsync(projectId, TenantApi.File("b2"), "GuV.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

        var again = await api.PatchDocumentsAsync(projectId, first, second);
        var onlySecond = await api.PatchDocumentsAsync(projectId, second);
        var none = await api.PatchDocumentsAsync(projectId);

        foreach (var response in new[] { again, onlySecond, none }) {
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Equal([first, second], Documents(await TenantApi.ReadJsonAsync(response)));
        }

        await using var db = api.CreateDb();
        Assert.Equal(2, await db.Documents.CountAsync(TestContext.Current.CancellationToken));
        Assert.Equal(2, await db.ProjectDocuments.CountAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC04_Patch_FieldsAndDocumentsTogether() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("c");
        var blobUrl = await api.UploadAsync(projectId, content, "Bilanz.pdf");
        var reference = new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Bilanz.pdf", content.Length, "application/pdf");

        var response = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{projectId}", new { name = "Mit Dokument", documents = new[] { reference } });

        var project = await TenantApi.ReadJsonAsync(response);
        Assert.Equal("Mit Dokument", project.GetProperty("name").GetString());
        Assert.Equal([reference], Documents(project));
    }

    [Fact]
    public async Task AC15_UrlWithTheSignedQuery_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("d");
        var blobUrl = await api.UploadAsync(projectId, content, "Bilanz.pdf");

        var response = await api.PatchDocumentsAsync(projectId, new DocumentRefBody(blobUrl, "Bilanz.pdf", content.Length, "application/pdf"));

        var errors = await TenantApi.ReadErrorsAsync(response);
        Assert.Equal(["must not contain a query or fragment"], errors["documents[0].url"]);
        Assert.DoesNotContain("sig=", JsonSerializer.Serialize(errors));
    }

    [Fact]
    public async Task AC15_UploadOfAnotherTenantOrHost_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        await using var other = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("e");
        var foreign = TenantApi.WithoutQuery(await other.UploadAsync(await other.CreateProjectAsync(), content, "Bilanz.pdf"));
        var otherHost = new UriBuilder(TenantApi.WithoutQuery(await api.UploadAsync(projectId, content, "Bilanz.pdf"))) { Host = "evil.example" }.Uri.AbsoluteUri;

        var response = await api.PatchDocumentsAsync(
            projectId,
            new DocumentRefBody(foreign, "Bilanz.pdf", content.Length, "application/pdf"),
            new DocumentRefBody(otherHost, "Bilanz.pdf", content.Length, "application/pdf"));

        Assert.Equal(
            new Dictionary<string, string[]> {
                ["documents[0].url"] = ["is not a document URL of this tenant"],
                ["documents[1].url"] = ["is not a document URL of this tenant"],
            },
            await TenantApi.ReadErrorsAsync(response));
        await using var db = api.CreateDb();
        Assert.False(await db.Documents.AnyAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC15_NewUploadOfAnotherProject_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var uploader = await api.CreateProjectAsync();
        var target = await api.CreateProjectAsync();
        var content = TenantApi.File("f");
        var blobUrl = await api.UploadAsync(uploader, content, "Bilanz.pdf");

        var response = await api.PatchDocumentsAsync(target, new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Bilanz.pdf", content.Length, "application/pdf"));

        Assert.Equal(["must be an upload of this project"], (await TenantApi.ReadErrorsAsync(response))["documents[0].url"]);
    }

    [Fact]
    public async Task AC15_UrlWithoutUploadedFile_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("g");
        var issued = await TenantApi.ReadJsonAsync(await api.RequestUploadUrlAsync(projectId, content, "Bilanz.pdf"));

        var response = await api.PatchDocumentsAsync(projectId, new DocumentRefBody(
            TenantApi.WithoutQuery(issued.GetProperty("blobUrl").GetString()!), "Bilanz.pdf", content.Length, "application/pdf"));

        Assert.Equal(["has no uploaded file"], (await TenantApi.ReadErrorsAsync(response))["documents[0].url"]);
    }

    [Fact]
    public async Task MetadataNotMatchingTheUpload_Returns400ListingEveryFailure_AndStoresNothing() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var valid = TenantApi.File("h1");
        var wrong = TenantApi.File("h2");
        var validUrl = TenantApi.WithoutQuery(await api.UploadAsync(projectId, valid, "Bilanz.pdf"));
        var wrongUrl = TenantApi.WithoutQuery(await api.UploadAsync(projectId, wrong, "GuV.pdf"));

        var response = await api.PatchDocumentsAsync(
            projectId,
            new DocumentRefBody(validUrl, "Bilanz.pdf", valid.Length, "application/pdf"),
            new DocumentRefBody(wrongUrl, "GuV.exe", wrong.Length + 1, "text/plain"));

        Assert.Equal(
            new Dictionary<string, string[]> {
                ["documents[1].size"] = ["does not match the uploaded file"],
                ["documents[1].contentType"] = ["does not match the uploaded file"],
                ["documents[1].name"] = ["must be a file name of at most 200 characters ending in .pdf, .doc, .docx, .xls or .xlsx"],
            },
            await TenantApi.ReadErrorsAsync(response));
        await using var db = api.CreateDb();
        Assert.False(await db.Documents.AnyAsync(TestContext.Current.CancellationToken));
        Assert.False(await db.ProjectDocuments.AnyAsync(TestContext.Current.CancellationToken));
        // A mismatch keeps the upload; the orphan cleanup removes it if it is never added.
        Assert.True(await api.Container.GetBlobClient($"{projectId}/{TenantApi.DocumentId(wrongUrl)}").ExistsAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC19_BlobLargerThan50MB_IsDeleted_AndThePatchReturns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var issued = await TenantApi.ReadJsonAsync(await api.RequestUploadUrlAsync(projectId, TenantApi.File("i"), "Groß.pdf"));
        var blobUrl = issued.GetProperty("blobUrl").GetString()!;
        // The upload URL cannot cap the size: a sparse page blob of 50 MB + 512 bytes is created through it.
        const long oversized = 52_428_800 + 512;
        await new PageBlobClient(new Uri(blobUrl)).CreateAsync(
            oversized, new PageBlobCreateOptions { HttpHeaders = new BlobHttpHeaders { ContentType = "application/pdf" } },
            TestContext.Current.CancellationToken);

        var response = await api.PatchDocumentsAsync(projectId, new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Groß.pdf", oversized, "application/pdf"));

        Assert.Equal(["exceeds the maximum of 52428800 bytes"], (await TenantApi.ReadErrorsAsync(response))["documents[0].size"]);
        Assert.False(await api.Container.GetBlobClient($"{projectId}/{TenantApi.DocumentId(blobUrl)}").ExistsAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC19_EmptyUpload_Returns400_AsAtTheUploadUrl_AndStoresNothing() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        // The upload URL is issued for at least one byte, but cannot stop an empty PUT.
        var issued = await TenantApi.ReadJsonAsync(await api.RequestUploadUrlAsync(projectId, TenantApi.File("p"), "Leer.pdf"));
        var blobUrl = issued.GetProperty("blobUrl").GetString()!;
        Assert.Equal(HttpStatusCode.Created, (await TenantApi.PutBlobAsync(blobUrl, [], "application/pdf")).StatusCode);

        var response = await api.PatchDocumentsAsync(projectId, new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Leer.pdf", 0, "application/pdf"));

        Assert.Equal(
            new Dictionary<string, string[]> { ["documents[0].size"] = ["must be an integer from 1 to 52428800"] },
            await TenantApi.ReadErrorsAsync(response));
        await using var db = api.CreateDb();
        Assert.False(await db.Documents.AnyAsync(TestContext.Current.CancellationToken));
        Assert.False(await db.ProjectDocuments.AnyAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Duplicate_SameContentNameAndSize_LinksTheStoredDocument_AndDeletesTheNewBlob() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var first = await api.CreateProjectAsync();
        var second = await api.CreateProjectAsync();
        var content = TenantApi.File("j");
        var stored = await api.AddDocumentAsync(first, content, "Bilanz.pdf");
        // The browser hash only serves the lookup; a wrong one gets a new URL for the same file.
        var issued = await TenantApi.ReadJsonAsync(await api.SendJsonAsync(HttpMethod.Post, $"{Base}/{second}/upload-url", new {
            sha256 = new string('0', 64),
            name = "Bilanz.pdf",
            size = content.Length,
            contentType = "application/pdf",
        }));
        var blobUrl = issued.GetProperty("blobUrl").GetString()!;
        Assert.Equal(HttpStatusCode.Created, (await TenantApi.PutBlobAsync(blobUrl, content, "application/pdf")).StatusCode);

        var response = await api.PatchDocumentsAsync(second, new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Bilanz.pdf", content.Length, "application/pdf"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal([stored], Documents(await TenantApi.ReadJsonAsync(response)));
        Assert.False(await api.Container.GetBlobClient($"{second}/{TenantApi.DocumentId(blobUrl)}").ExistsAsync(TestContext.Current.CancellationToken));
        await using var db = api.CreateDb();
        Assert.Equal(1, await db.Documents.CountAsync(TestContext.Current.CancellationToken));
        Assert.Equal(2, await db.ProjectDocuments.CountAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Duplicate_PatchSentAgainWithTheReplacedUpload_Returns400_AndChangesNothing() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var first = await api.CreateProjectAsync();
        var second = await api.CreateProjectAsync();
        var content = TenantApi.File("q");
        var stored = await api.AddDocumentAsync(first, content, "Bilanz.pdf");
        var issued = await TenantApi.ReadJsonAsync(await api.SendJsonAsync(HttpMethod.Post, $"{Base}/{second}/upload-url", new {
            sha256 = new string('0', 64),
            name = "Bilanz.pdf",
            size = content.Length,
            contentType = "application/pdf",
        }));
        var blobUrl = issued.GetProperty("blobUrl").GetString()!;
        Assert.Equal(HttpStatusCode.Created, (await TenantApi.PutBlobAsync(blobUrl, content, "application/pdf")).StatusCode);
        var body = new { name = "Zweites Projekt", documents = new[] { new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), "Bilanz.pdf", content.Length, "application/pdf") } };
        Assert.Equal(HttpStatusCode.OK, (await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{second}", body)).StatusCode);

        // Accepted limitation (the plan deletes the duplicate blob after the commit): the replay finds neither a
        // document nor a blob for the replaced upload. It fails as a whole and changes nothing.
        var replay = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{second}", body with { name = "Nicht übernommen" });

        Assert.Equal(new Dictionary<string, string[]> { ["documents[0].url"] = ["has no uploaded file"] }, await TenantApi.ReadErrorsAsync(replay));
        var project = await api.GetProjectAsync(second);
        Assert.Equal("Zweites Projekt", project.GetProperty("name").GetString());
        Assert.Equal([stored], Documents(project));
        await using var db = api.CreateDb();
        Assert.Equal(1, await db.Documents.CountAsync(TestContext.Current.CancellationToken));
        Assert.Equal(2, await db.ProjectDocuments.CountAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Collision_SameHashWithAnotherName_IsStoredAsASeparateDocument() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var content = TenantApi.File("k");
        var original = await api.AddDocumentAsync(projectId, content, "Bilanz.pdf");

        var copy = await api.AddDocumentAsync(projectId, content, "Bilanz Kopie.pdf");

        Assert.Equal([original, copy], Documents(await api.GetProjectAsync(projectId)));
        await using var db = api.CreateDb();
        var hashes = await db.Documents.Select(document => document.Sha256).ToListAsync(TestContext.Current.CancellationToken);
        Assert.Equal(2, hashes.Count);
        Assert.Equal(hashes[0], hashes[1]);
    }

    [Fact]
    public async Task CrossProject_KnownDocumentOfAnotherProject_IsLinked() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var first = await api.CreateProjectAsync();
        var second = await api.CreateProjectAsync();
        var stored = await api.AddDocumentAsync(first, TenantApi.File("l"), "Bilanz.pdf");

        var response = await api.PatchDocumentsAsync(second, stored);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal([stored], Documents(await TenantApi.ReadJsonAsync(response)));
        Assert.Equal([stored], Documents(await api.GetProjectAsync(first)));
        await using var db = api.CreateDb();
        Assert.Equal(1, await db.Documents.CountAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task KnownDocument_WithOtherMetadata_Returns400_DocumentsNeverChange() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var stored = await api.AddDocumentAsync(projectId, TenantApi.File("m"), "Bilanz.pdf");

        var response = await api.PatchDocumentsAsync(projectId, stored with { Name = "Umbenannt.pdf", Size = stored.Size + 1 });

        var errors = await TenantApi.ReadErrorsAsync(response);
        Assert.Equal(["documents[0].name", "documents[0].size"], errors.Keys.Order());
        Assert.All(errors.Values, reasons => Assert.Equal(["does not match the stored document; documents never change"], reasons));
        Assert.Equal([stored], Documents(await api.GetProjectAsync(projectId)));
    }

    [Fact]
    public async Task SameDocumentTwiceWithOtherValues_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var stored = await api.AddDocumentAsync(projectId, TenantApi.File("n"), "Bilanz.pdf");

        var same = await api.PatchDocumentsAsync(projectId, stored, stored);
        var other = await api.PatchDocumentsAsync(projectId, stored, stored with { Name = "Anders.pdf" });

        Assert.Equal(HttpStatusCode.OK, same.StatusCode);
        Assert.Equal(["is also in documents[0] with other values"], (await TenantApi.ReadErrorsAsync(other))["documents[1].url"]);
    }

    private static List<DocumentRefBody> Documents(JsonElement project) =>
        project.GetProperty("documents").Deserialize<List<DocumentRefBody>>(JsonSerializerOptions.Web)!;
}
