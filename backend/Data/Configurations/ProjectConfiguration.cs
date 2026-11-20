using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Aicepeak.Api.Data.Configurations;

/// <summary>
/// Project names are unique ignoring case: PostgreSQL keeps <c>name_normalized = lower(name)</c> in a stored generated
/// column (a shadow property, never set by the app) with the unique index <see cref="NameIndex"/>.
/// </summary>
internal sealed class ProjectConfiguration : IEntityTypeConfiguration<Project> {
    public const string NameIndex = "IX_projects_name_normalized";

    private const string NormalizedName = "NameNormalized";

    public void Configure(EntityTypeBuilder<Project> builder) {
        builder.ToTable("projects");
        builder.HasKey(project => project.Id);
        builder.Property(project => project.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(project => project.Name).HasColumnName("name").HasMaxLength(Project.MaxNameLength);
        builder.Property(project => project.StartDate).HasColumnName("start_date");
        builder.Property(project => project.EndDate).HasColumnName("end_date");
        builder.Property(project => project.Description).HasColumnName("description").HasMaxLength(Project.MaxDescriptionLength);
        builder.Property<string>(NormalizedName).HasColumnName("name_normalized").IsRequired()
            .HasComputedColumnSql("lower(name)", stored: true);
        builder.HasIndex(NormalizedName).IsUnique().HasDatabaseName(NameIndex);
    }
}
