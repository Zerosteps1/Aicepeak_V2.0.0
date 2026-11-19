using System.Security.Claims;
using Aicepeak.Api.Auth;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Documents.Analysis;
using Aicepeak.Api.Storage;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Aicepeak.Api.Projects;

/// <summary>
/// Projects of the caller's tenant with their documents, under <c>/project</c>. User tokens only
/// (<see cref="TenantEndpointFilter"/>). Route IDs have no route constraint: an ID that is not a GUID is 404 after
/// authentication. Bodies are read as JSON documents, so a missing property and <c>null</c> stay distinct, and every
/// 400 is one ValidationProblem listing all failures.
/// </summary>
public static class ProjectEndpoints {
    public const string BasePath = "/api/v1/project";

    private const string NameTaken = "is already used by another project";
    private const string ProjectNameIndex = "IX_projects_name";

    public static RouteGroupBuilder MapProjects(this RouteGroupBuilder group) {
        var projects = group.MapGroup("/project").AddEndpointFilter<TenantEndpointFilter>();
        projects.MapPost("", CreateAsync);
        projects.MapGet("/{id}", GetAsync);
        projects.MapPatch("/{id}", UpdateAsync);
        projects.MapPost("/{id}/upload-url", CreateUploadUrlAsync);
        projects.MapDelete("/{id}/document/{documentId}", DeleteDocumentAsync);
        projects.MapGet("/{id}/document-validation/sse", ValidationEventsAsync);
        projects.MapGet("/{id}/document-extraction/sse", ExtractionEventsAsync);

        return group;
    }

    /// <summary><c>POST /project</c>: <c>{name, startDate, endDate?, description?}</c>; 201 with the project.</summary>
    private static async Task<Results<Created<ProjectResponse>, ValidationProblem, StatusCodeHttpResult>> CreateAsync(
        HttpRequest request, TenantDbContext db, CancellationToken cancellationToken) {
        if (!request.HasJsonContentType()) {
            return TypedResults.StatusCode(StatusCodes.Status415UnsupportedMediaType);
        }

        var errors = new ValidationErrors();
        using var body = await errors.ReadObjectAsync(request, cancellationToken);
        if (body is null) {
            return errors.ToProblem();
        }

        var input = ProjectInput.ParseCreate(body.RootElement, errors);
        if (input.Name is { } name && await db.Projects.AnyAsync(project => project.Name == name, cancellationToken)) {
            errors.Add("name", NameTaken);
        }

        if (errors.Any) {
            return errors.ToProblem();
        }

        var project = new Project {
            Id = Guid.CreateVersion7(),
            Name = input.Name!,
            StartDate = input.StartDate!.Value,
            EndDate = input.EndDate,
            Description = input.Description ?? "",
        };
        db.Projects.Add(project);
        try {
            await db.SaveChangesAsync(cancellationToken);
        } catch (DbUpdateException exception) when (IsNameTaken(exception)) {
            errors.Add("name", NameTaken);
            return errors.ToProblem();
        }

        return TypedResults.Created($"{BasePath}/{project.Id}", new ProjectResponse(
            project.Id, project.Name, project.StartDate, project.EndDate, project.Description, []));
    }

    /// <summary><c>GET /project/{id}</c>: the project with its documents.</summary>
    private static async Task<Results<Ok<ProjectResponse>, NotFound>> GetAsync(
        string id, ClaimsPrincipal principal, TenantDbContext db, DocumentBlobs blobs, CancellationToken cancellationToken) {
        if (!Guid.TryParse(id, out var projectId)
            || await db.Projects.AsNoTracking().SingleOrDefaultAsync(project => project.Id == projectId, cancellationToken) is not { } project) {
            return TypedResults.NotFound();
        }

        return TypedResults.Ok(await ResponseAsync(db, blobs, TenantId(principal), project, cancellationToken));
    }

    /// <summary>
    /// <c>PATCH /project/{id}</c>: any subset of <c>{name, startDate, endDate, description, documents}</c>;
    /// <c>endDate: null</c> clears it. <c>documents</c> only adds (see <see cref="ProjectDocumentLinker"/>). Everything is
    /// validated first and saved in one transaction; replaced duplicate blobs are deleted after the commit.
    /// </summary>
    private static async Task<Results<Ok<ProjectResponse>, NotFound, ValidationProblem, StatusCodeHttpResult>> UpdateAsync(
        string id,
        HttpRequest request,
        ClaimsPrincipal principal,
        TenantDbContext db,
        DocumentBlobs blobs,
        TimeProvider time,
        ILoggerFactory loggers,
        CancellationToken cancellationToken) {
        if (!Guid.TryParse(id, out var projectId)) {
            return TypedResults.NotFound();
        }

        if (!request.HasJsonContentType()) {
            return TypedResults.StatusCode(StatusCodes.Status415UnsupportedMediaType);
        }

        var errors = new ValidationErrors();
        using var body = await errors.ReadObjectAsync(request, cancellationToken);
        if (body is null) {
            return errors.ToProblem();
        }

        var tid = TenantId(principal);
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (await LockProjectAsync(db, projectId, cancellationToken) is not { } project) {
            return TypedResults.NotFound();
        }

        var input = ProjectInput.ParseUpdate(body.RootElement, projectId, errors);
        input.CheckDates(project.StartDate, project.EndDate, errors);
        if (input.Name is { } name
            && await db.Projects.AnyAsync(other => other.Name == name && other.Id != projectId, cancellationToken)) {
            errors.Add("name", NameTaken);
        }

        IReadOnlyList<string> duplicateBlobs = [];
        if (input.Documents is { } documents) {
            var linker = new ProjectDocumentLinker(db, blobs, time, tid, projectId);
            duplicateBlobs = await linker.AddAsync(documents, errors, cancellationToken);
        }

        if (errors.Any) {
            return errors.ToProblem();
        }

        project.Name = input.Name ?? project.Name;
        project.StartDate = input.StartDate ?? project.StartDate;
        project.EndDate = input.HasEndDate ? input.EndDate : project.EndDate;
        project.Description = input.Description ?? project.Description;
        try {
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
        } catch (DbUpdateException exception) when (IsNameTaken(exception)) {
            errors.Add("name", NameTaken);
            return errors.ToProblem();
        }

        await DeleteDuplicateBlobsAsync(blobs, tid, duplicateBlobs, loggers);
        return TypedResults.Ok(await ResponseAsync(db, blobs, tid, project, cancellationToken));
    }

    /// <summary>
    /// <c>POST /project/{id}/upload-url</c>: <c>{sha256, name, size, contentType}</c>. If the tenant has a document with the
    /// same SHA-256, name and size, returns <c>{document}</c> instead of an upload URL; otherwise a new document ID and
    /// <c>{blobUrl, expires}</c>. Nothing is stored until the PATCH.
    /// </summary>
    private static async Task<Results<Ok<UploadUrlResponse>, Ok<DuplicateDocumentResponse>, NotFound, ValidationProblem, StatusCodeHttpResult>>
        CreateUploadUrlAsync(
            string id, HttpRequest request, ClaimsPrincipal principal, TenantDbContext db, DocumentBlobs blobs, CancellationToken cancellationToken) {
        if (!Guid.TryParse(id, out var projectId)) {
            return TypedResults.NotFound();
        }

        if (!request.HasJsonContentType()) {
            return TypedResults.StatusCode(StatusCodes.Status415UnsupportedMediaType);
        }

        var errors = new ValidationErrors();
        using var body = await errors.ReadObjectAsync(request, cancellationToken);
        if (body is null) {
            return errors.ToProblem();
        }

        if (!await db.Projects.AnyAsync(project => project.Id == projectId, cancellationToken)) {
            return TypedResults.NotFound();
        }

        if (UploadUrlInput.Parse(body.RootElement, errors) is not { } input) {
            return errors.ToProblem();
        }

        var tid = TenantId(principal);
        var duplicate = await db.Documents.AsNoTracking()
            .Where(document => document.Sha256 == input.Sha256 && document.Name == input.Name && document.Size == input.Size)
            .OrderBy(document => document.CreatedAt)
            .ThenBy(document => document.Id)
            .FirstOrDefaultAsync(cancellationToken);
        if (duplicate is not null) {
            return TypedResults.Ok(new DuplicateDocumentResponse(Ref(blobs, tid, duplicate)));
        }

        var (url, expires) = await blobs.CreateUploadUrlAsync(tid, projectId, Guid.CreateVersion7(), cancellationToken);
        return TypedResults.Ok(new UploadUrlResponse(url.AbsoluteUri, expires));
    }

    /// <summary>
    /// <c>DELETE /project/{id}/document/{documentId}</c>: removes the project's link. If no other project links the
    /// document, its row and then its blob are deleted as well, in the same transaction: if the blob cannot be deleted,
    /// nothing changes. 404 if the link does not exist.
    /// </summary>
    private static async Task<Results<NoContent, NotFound>> DeleteDocumentAsync(
        string id, string documentId, ClaimsPrincipal principal, TenantDbContext db, DocumentBlobs blobs, CancellationToken cancellationToken) {
        if (!Guid.TryParse(id, out var projectId) || !Guid.TryParse(documentId, out var docId)) {
            return TypedResults.NotFound();
        }

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (await LockProjectAsync(db, projectId, cancellationToken) is null
            || await db.ProjectDocuments.SingleOrDefaultAsync(link => link.ProjectId == projectId && link.DocumentId == docId, cancellationToken)
                is not { } link) {
            return TypedResults.NotFound();
        }

        // FOR UPDATE: a concurrent PATCH linking this document waits, or is waited for and then counted below.
        var document = (await db.Documents.FromSql($"SELECT * FROM documents WHERE id = {docId} FOR UPDATE").ToListAsync(cancellationToken)).Single();
        db.ProjectDocuments.Remove(link);
        await db.SaveChangesAsync(cancellationToken);
        if (!await db.ProjectDocuments.AnyAsync(other => other.DocumentId == docId, cancellationToken)) {
            db.Documents.Remove(document);
            await db.SaveChangesAsync(cancellationToken);
            // From here on the request finishes even if the client goes away: a deleted blob needs the commit.
            await blobs.DeleteAsync(TenantId(principal), document.BlobName, CancellationToken.None);
        }

        await transaction.CommitAsync(CancellationToken.None);
        return TypedResults.NoContent();
    }

    /// <summary><c>GET /project/{id}/document-validation/sse</c>: validation progress of the project's documents.</summary>
    private static async Task<Results<ServerSentEventsResult<DocumentProgressEvent>, NotFound>> ValidationEventsAsync(
        string id, TenantDbContext db, DocumentAnalyzer analyzer, CancellationToken cancellationToken) =>
        await DocumentsAsync(db, id, cancellationToken) is { } documents
            ? TypedResults.ServerSentEvents(analyzer.ValidateAsync(documents, cancellationToken))
            : TypedResults.NotFound();

    /// <summary><c>GET /project/{id}/document-extraction/sse</c>: extraction progress of the project's documents.</summary>
    private static async Task<Results<ServerSentEventsResult<DocumentProgressEvent>, NotFound>> ExtractionEventsAsync(
        string id, TenantDbContext db, DocumentAnalyzer analyzer, CancellationToken cancellationToken) =>
        await DocumentsAsync(db, id, cancellationToken) is { } documents
            ? TypedResults.ServerSentEvents(analyzer.ExtractAsync(documents, cancellationToken))
            : TypedResults.NotFound();

    /// <summary>The documents linked to the project, or <c>null</c> if it does not exist.</summary>
    private static async Task<List<Document>?> DocumentsAsync(TenantDbContext db, string id, CancellationToken cancellationToken) {
        if (!Guid.TryParse(id, out var projectId) || !await db.Projects.AnyAsync(project => project.Id == projectId, cancellationToken)) {
            return null;
        }

        return await db.DocumentsOf(projectId).AsNoTracking().ToListAsync(cancellationToken);
    }

    /// <summary>The project row, locked until the transaction ends, so changes of one project never interleave.</summary>
    private static async Task<Project?> LockProjectAsync(TenantDbContext db, Guid projectId, CancellationToken cancellationToken) =>
        (await db.Projects.FromSql($"SELECT * FROM projects WHERE id = {projectId} FOR UPDATE").ToListAsync(cancellationToken))
        .SingleOrDefault();

    private static async Task<ProjectResponse> ResponseAsync(
        TenantDbContext db, DocumentBlobs blobs, Guid tid, Project project, CancellationToken cancellationToken) {
        var documents = await db.DocumentsOf(project.Id).AsNoTracking().ToListAsync(cancellationToken);
        return new ProjectResponse(
            project.Id, project.Name, project.StartDate, project.EndDate, project.Description,
            documents.Select(document => Ref(blobs, tid, document)).ToList());
    }

    private static DocumentRef Ref(DocumentBlobs blobs, Guid tid, Document document) =>
        new(blobs.GetUrl(tid, document.BlobName).AbsoluteUri, document.Name, document.Size, document.ContentType);

    /// <summary>Best effort: a blob left behind has no document row, so the weekly orphan cleanup removes it.</summary>
    private static async Task DeleteDuplicateBlobsAsync(DocumentBlobs blobs, Guid tid, IReadOnlyList<string> blobNames, ILoggerFactory loggers) {
        foreach (var blobName in blobNames) {
            try {
                await blobs.DeleteAsync(tid, blobName, CancellationToken.None);
            } catch (Exception exception) {
                loggers.CreateLogger(typeof(ProjectEndpoints)).LogWarning(
                    "A duplicate upload of tenant {Tid} could not be deleted: {Failure}.", tid, exception.GetType().Name);
            }
        }
    }

    /// <summary>The caller's tenant; <see cref="TenantEndpointFilter"/> admitted only callers that have one.</summary>
    private static Guid TenantId(ClaimsPrincipal principal) =>
        EntraAuthentication.TryGetTenantId(principal, out var tid)
            ? tid
            : throw new InvalidOperationException("The caller has no tenant; the endpoint lacks the TenantEndpointFilter.");

    private static bool IsNameTaken(DbUpdateException exception) =>
        exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation, ConstraintName: ProjectNameIndex };
}
