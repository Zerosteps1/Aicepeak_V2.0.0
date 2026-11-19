using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Aicepeak.Api.Data.Configurations;

internal sealed class DocumentConfiguration : IEntityTypeConfiguration<Document> {
    public void Configure(EntityTypeBuilder<Document> builder) {
        builder.ToTable("documents", table => table.HasCheckConstraint(
            "CK_documents_sha256_length", $"octet_length(sha256) = {Document.Sha256Length}"));
        builder.HasKey(document => document.Id);
        builder.Property(document => document.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(document => document.ProjectId).HasColumnName("project_id");
        builder.Property(document => document.BlobName).HasColumnName("blob_name").HasMaxLength(200);
        builder.Property(document => document.Name).HasColumnName("name").HasMaxLength(Document.MaxNameLength);
        builder.Property(document => document.Size).HasColumnName("size");
        builder.Property(document => document.ContentType).HasColumnName("content_type").HasMaxLength(Document.MaxContentTypeLength);
        builder.Property(document => document.Sha256).HasColumnName("sha256").HasMaxLength(Document.Sha256Length);
        builder.Property(document => document.CreatedAt).HasColumnName("created_at");
        builder.HasIndex(document => document.BlobName).IsUnique();
        // Duplicate lookup by content; equal hashes with another name or size are separate documents.
        builder.HasIndex(document => document.Sha256);
        // The uploading project; a document has no navigation to it, and a referenced project cannot be deleted.
        builder.HasOne<Project>().WithMany().HasForeignKey(document => document.ProjectId).OnDelete(DeleteBehavior.Restrict);
    }
}
