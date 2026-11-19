using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Aicepeak.Api.Data.Configurations;

internal sealed class ProjectConfiguration : IEntityTypeConfiguration<Project> {
    public void Configure(EntityTypeBuilder<Project> builder) {
        builder.ToTable("projects");
        builder.HasKey(project => project.Id);
        builder.Property(project => project.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(project => project.Name).HasColumnName("name").HasMaxLength(Project.MaxNameLength);
        builder.Property(project => project.StartDate).HasColumnName("start_date");
        builder.Property(project => project.EndDate).HasColumnName("end_date");
        builder.Property(project => project.Description).HasColumnName("description").HasMaxLength(Project.MaxDescriptionLength);
        builder.HasIndex(project => project.Name).IsUnique();
    }
}
