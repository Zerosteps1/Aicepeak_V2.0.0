using System.Net;
using System.Text.Json;
using Aicepeak.Api.Documents.Analysis.Mock;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// The whole document flow as the frontend drives it, against PostgreSQL and Azurite (Docker): create a project, get
/// upload URLs, PUT the files to the storage, add them with one PATCH, validate, remove the invalid document, extract,
/// and remove the rest.
/// </summary>
[Collection(StorageCollection.Name)]
[Trait("Category", "Database")]
public sealed class DocumentFlowEndToEndTests(PostgresFixture postgres, AzuriteFixture azurite) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task CreateUploadPatchValidateDeleteExtract() {
        var ct = TestContext.Current.CancellationToken;
        await using var api = await TenantApi.CreateAsync(postgres, azurite);

        // 1. Create the project.
        var created = await api.SendJsonAsync(HttpMethod.Post, Base, new { name = "Neues Projekt 19.11.2026 10:00:00", startDate = "2026-11-19", endDate = (string?)null, description = "" });
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        var projectId = (await TenantApi.ReadJsonAsync(created)).GetProperty("id").GetGuid();

        // 2. + 3. Upload URLs, then PUT the files directly to the storage.
        var files = new[] {
            (Name: "Jahresabschluss 2025.pdf", Content: TenantApi.File("report", 120_000), Type: "application/pdf"),
            (Name: "invalid-Scan.docx", Content: TenantApi.File("scan"), Type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        };
        var references = new List<DocumentRefBody>();
        foreach (var (name, content, type) in files) {
            var blobUrl = await api.UploadAsync(projectId, content, name, type);
            references.Add(new DocumentRefBody(TenantApi.WithoutQuery(blobUrl), name, content.Length, type));
        }

        // 4. One PATCH with all references, the signed query stripped.
        var patched = await api.PatchDocumentsAsync(projectId, [.. references]);
        Assert.Equal(HttpStatusCode.OK, patched.StatusCode);
        Assert.Equal(references, Documents(await TenantApi.ReadJsonAsync(patched)));
        var (reportId, scanId) = (TenantApi.DocumentId(references[0].Url), TenantApi.DocumentId(references[1].Url));

        // 5. Validation: the scan is invalid.
        var validation = await ServerSentEvents.ReadAsync(await api.Client.GetAsync($"{Base}/{projectId}/document-validation/sse", ct));
        Assert.Equal(100, validation[^1].Int("overallProgress"));
        Assert.Equal(
            [scanId],
            validation.Where(item => item.String("error") == MockDocumentValidator.InvalidError).Select(item => item.String("document")));

        // 6. Remove the invalid document; its blob goes too.
        Assert.Equal(HttpStatusCode.NoContent, (await api.Client.DeleteAsync($"{Base}/{projectId}/document/{scanId}", ct)).StatusCode);
        Assert.Equal([references[0]], Documents(await api.GetProjectAsync(projectId)));

        // 7. Extraction of the remaining document.
        var extraction = await ServerSentEvents.ReadAsync(await api.Client.GetAsync($"{Base}/{projectId}/document-extraction/sse", ct));
        Assert.All(extraction, item => Assert.Equal(reportId, item.String("document")));
        Assert.Equal(100, extraction[^1].Int("overallProgress"));
        Assert.Equal(extraction[^1].Int("pages"), extraction[^1].Int("pagesRead"));

        // 8. Remove the last document: nothing is left in the storage.
        Assert.Equal(HttpStatusCode.NoContent, (await api.Client.DeleteAsync($"{Base}/{projectId}/document/{reportId}", ct)).StatusCode);
        Assert.Empty(Documents(await api.GetProjectAsync(projectId)));
        var remaining = new List<string>();
        await foreach (var blob in api.Container.GetBlobsAsync(new Azure.Storage.Blobs.Models.GetBlobsOptions(), ct)) {
            remaining.Add(blob.Name);
        }

        Assert.Empty(remaining);
    }

    private static List<DocumentRefBody> Documents(JsonElement project) =>
        project.GetProperty("documents").Deserialize<List<DocumentRefBody>>(JsonSerializerOptions.Web)!;
}
