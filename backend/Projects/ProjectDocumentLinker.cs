using System.Security.Cryptography;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Storage;
using Microsoft.EntityFrameworkCore;

namespace Aicepeak.Api.Projects;

/// <summary>
/// Adds the <c>documents</c> of a PATCH to a project; documents are only ever added here, removal is
/// <c>DELETE /project/{id}/document/{documentId}</c>. For each reference:
/// <list type="bullet">
/// <item>A document the tenant already has must match its stored URL, name, size and content type (documents never
/// change); it is linked to the project if it is not yet.</item>
/// <item>A new document must be an upload of this project (<c>&lt;tid&gt;/&lt;projectId&gt;/</c>) whose blob exists, has
/// the given size (1 byte to 50 MB, as at the upload URL; a larger blob is deleted) and content type, under a valid
/// name. The backend hashes the blob; if the tenant has a document with the same hash, name and size, that one is
/// linked and the new blob is deleted after commit, otherwise a new document is stored.</item>
/// </list>
/// Runs inside the caller's transaction, after the project row was locked; the caller saves only without failures.
/// <para>
/// Known limitation (the plan deletes duplicate blobs right after the commit): a PATCH sent again with the URL of an
/// upload that was replaced by a stored duplicate finds neither a document nor a blob, so it answers 400 ("has no
/// uploaded file") and changes nothing. Clients send the reference from the PATCH response instead.
/// </para>
/// </summary>
internal sealed class ProjectDocumentLinker(TenantDbContext db, DocumentBlobs blobs, TimeProvider time, Guid tid, Guid projectId) {
    private const string Immutable = "does not match the stored document; documents never change";
    private const string NotUploaded = "does not match the uploaded file";

    private sealed record Upload(DocumentRefInput Entry, Guid DocumentId, string BlobName, byte[] Sha256);

    /// <summary>Validates and stages all references; returns the blobs to delete once the transaction committed.</summary>
    public async Task<IReadOnlyList<string>> AddAsync(
        IReadOnlyList<DocumentRefInput> entries, ValidationErrors errors, CancellationToken cancellationToken) {
        var parsed = Distinct(entries, errors);
        var ids = parsed.Select(entry => entry.DocumentId).ToArray();
        // FOR SHARE: a concurrent DELETE of the last link cannot remove a document this request links.
        var known = (await db.Documents.FromSql($"SELECT * FROM documents WHERE id = ANY({ids}) FOR SHARE").ToListAsync(cancellationToken))
            .ToDictionary(document => document.Id);
        var linked = (await db.ProjectDocuments.Where(link => link.ProjectId == projectId).Select(link => link.DocumentId)
            .ToListAsync(cancellationToken)).ToHashSet();

        var uploads = new List<Upload>();
        foreach (var (entry, urlProjectId, documentId) in parsed) {
            if (known.TryGetValue(documentId, out var document)) {
                if (MatchesStored(entry, document, errors)) {
                    Link(documentId, linked);
                }
            } else if (await CheckUploadAsync(entry, urlProjectId, documentId, errors, cancellationToken) is { } upload) {
                uploads.Add(upload);
            }
        }

        if (errors.Any) {
            return [];
        }

        var duplicateBlobs = new List<string>();
        var stored = new List<Document>();
        foreach (var upload in uploads) {
            var entry = upload.Entry;
            var existing = stored.FirstOrDefault(document => IsSameFile(document, upload))
                ?? (await db.Documents.FromSql(
                        $"SELECT * FROM documents WHERE sha256 = {upload.Sha256} AND name = {entry.Name} AND size = {entry.Size} ORDER BY created_at, id LIMIT 1 FOR SHARE")
                    .ToListAsync(cancellationToken)).SingleOrDefault();
            if (existing is not null) {
                duplicateBlobs.Add(upload.BlobName);
                Link(existing.Id, linked);
                continue;
            }

            var document = new Document {
                Id = upload.DocumentId,
                ProjectId = projectId,
                BlobName = upload.BlobName,
                Name = entry.Name,
                Size = entry.Size,
                ContentType = entry.ContentType,
                Sha256 = upload.Sha256,
                CreatedAt = time.GetUtcNow(),
            };
            db.Documents.Add(document);
            stored.Add(document);
            Link(document.Id, linked);
        }

        return duplicateBlobs;
    }

    /// <summary>Entries with a document URL of this tenant; the same document twice must be the same entry.</summary>
    private List<(DocumentRefInput Entry, Guid UrlProjectId, Guid DocumentId)> Distinct(
        IReadOnlyList<DocumentRefInput> entries, ValidationErrors errors) {
        var result = new List<(DocumentRefInput, Guid, Guid)>();
        var first = new Dictionary<Guid, DocumentRefInput>();
        foreach (var entry in entries) {
            if (!blobs.TryParseUrl(entry.Url, tid, out var urlProjectId, out var documentId)) {
                errors.Add(entry.Field("url"), "is not a document URL of this tenant");
            } else if (!first.TryGetValue(documentId, out var earlier)) {
                first[documentId] = entry;
                result.Add((entry, urlProjectId, documentId));
            } else if (earlier with { Index = entry.Index } != entry) {
                errors.Add(entry.Field("url"), $"is also in documents[{earlier.Index}] with other values");
            }
        }

        return result;
    }

    private bool MatchesStored(DocumentRefInput entry, Document document, ValidationErrors errors) {
        var matches = true;
        foreach (var (property, equal) in new[] {
                     ("url", entry.Url.AbsoluteUri == blobs.GetUrl(tid, document.BlobName).AbsoluteUri),
                     ("name", entry.Name == document.Name),
                     ("size", entry.Size == document.Size),
                     ("contentType", entry.ContentType == document.ContentType),
                 }) {
            if (!equal) {
                errors.Add(entry.Field(property), Immutable);
                matches = false;
            }
        }

        return matches;
    }

    /// <summary>The checks of a new upload in the documented order; <c>null</c> with failures added if one fails.</summary>
    private async Task<Upload?> CheckUploadAsync(
        DocumentRefInput entry, Guid urlProjectId, Guid documentId, ValidationErrors errors, CancellationToken cancellationToken) {
        if (urlProjectId != projectId) {
            errors.Add(entry.Field("url"), "must be an upload of this project");
            return null;
        }

        var blobName = DocumentBlobs.BlobName(projectId, documentId);
        var blob = await blobs.GetInfoAsync(tid, blobName, cancellationToken);
        if (blob is null) {
            errors.Add(entry.Field("url"), "has no uploaded file");
            return null;
        }

        if (blob.Size > DocumentBlobs.MaxSize) {
            // An upload URL cannot cap the size; an oversized file is removed right away.
            await blobs.DeleteAsync(tid, blobName, cancellationToken);
            errors.Add(entry.Field("size"), $"exceeds the maximum of {DocumentBlobs.MaxSize} bytes");
            return null;
        }

        var valid = true;
        if (entry.Size != blob.Size) {
            errors.Add(entry.Field("size"), NotUploaded);
            valid = false;
        } else if (!DocumentRules.IsValidSize(blob.Size)) {
            // An empty file: the upload URL was issued for at least one byte, but cannot stop an empty PUT.
            errors.Add(entry.Field("size"), DocumentRules.SizeRule);
            valid = false;
        }

        if (entry.ContentType != blob.ContentType) {
            errors.Add(entry.Field("contentType"), NotUploaded);
            valid = false;
        } else if (!DocumentRules.IsValidContentType(entry.ContentType)) {
            errors.Add(entry.Field("contentType"), DocumentRules.ContentTypeRule);
            valid = false;
        }

        if (!DocumentRules.IsValidName(entry.Name)) {
            errors.Add(entry.Field("name"), DocumentRules.NameRule);
            valid = false;
        }

        if (!valid) {
            return null;
        }

        var sha256 = await HashAsync(blobName, blob.Size, cancellationToken);
        if (sha256 is null) {
            errors.Add(entry.Field("size"), NotUploaded);
            return null;
        }

        return new Upload(entry, documentId, blobName, sha256);
    }

    /// <summary>SHA-256 of the blob, streamed; <c>null</c> if its content does not have the expected length.</summary>
    private async Task<byte[]?> HashAsync(string blobName, long expectedSize, CancellationToken cancellationToken) {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[81920];
        long read = 0;
        await using var content = await blobs.OpenReadAsync(tid, blobName, cancellationToken);
        int count;
        while ((count = await content.ReadAsync(buffer, cancellationToken)) > 0) {
            read += count;
            if (read > expectedSize) {
                return null;
            }

            hash.AppendData(buffer, 0, count);
        }

        return read == expectedSize ? hash.GetHashAndReset() : null;
    }

    private static bool IsSameFile(Document document, Upload upload) =>
        document.Sha256.AsSpan().SequenceEqual(upload.Sha256) && document.Name == upload.Entry.Name && document.Size == upload.Entry.Size;

    private void Link(Guid documentId, HashSet<Guid> linked) {
        if (linked.Add(documentId)) {
            db.ProjectDocuments.Add(new ProjectDocument { ProjectId = projectId, DocumentId = documentId });
        }
    }
}
