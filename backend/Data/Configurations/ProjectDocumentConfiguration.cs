using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Aicepeak.Api.Data.Configurations;

/// <summary>The m-n join table; PostgreSQL has no foreign keys on array elements.</summary>
internal sealed class ProjectDocumentConfiguration : IEntityTypeConfiguration<ProjectDocument> {
    public void Configure(EntityTypeBuilder<ProjectDocument> builder) {
        builder.ToTable("project_documents");
        builder.HasKey(link => new { link.ProjectId, link.DocumentId });
        builder.Property(link => link.ProjectId).HasColumnName("project_id");
        builder.Property(link => link.DocumentId).HasColumnName("document_id");
        builder.HasOne<Project>().WithMany().HasForeignKey(link => link.ProjectId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Document>().WithMany().HasForeignKey(link => link.DocumentId).OnDelete(DeleteBehavior.Cascade);
    }
}
