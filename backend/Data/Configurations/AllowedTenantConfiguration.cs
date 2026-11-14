using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Aicepeak.Api.Data.Configurations;

internal sealed class AllowedTenantConfiguration : IEntityTypeConfiguration<AllowedTenant> {
    /// <summary>The tenant allowed from the start; further tenants are added in the database.</summary>
    public static readonly Guid DefaultTenant = new("db760528-cb7c-455c-bd41-e50a38f6fd62");

    public void Configure(EntityTypeBuilder<AllowedTenant> builder) {
        builder.ToTable("allowed_tenants");
        builder.HasKey(tenant => tenant.Tid);
        builder.Property(tenant => tenant.Tid).HasColumnName("tid").ValueGeneratedNever();
        builder.HasData(new AllowedTenant { Tid = DefaultTenant });
    }
}
