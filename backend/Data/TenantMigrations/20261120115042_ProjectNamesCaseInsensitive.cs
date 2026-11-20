using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Aicepeak.Api.Data.TenantMigrations
{
    /// <inheritdoc />
    public partial class ProjectNamesCaseInsensitive : Migration
    {
        /// <summary>Start of the error (SQLSTATE P0001) for projects whose names differ only in case; their IDs follow.</summary>
        internal const string DuplicateNamesMessage =
            "Project names must be unique ignoring case. Rename all but one project of each group before migrating: ";

        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Names differing only in case were allowed before, and the unique index cannot be built over them. Fail
            // first with the project IDs per shared name (not the names, which are tenant data) instead of with the
            // index's bare unique violation. Renaming them is left to the tenant; no name is changed here.
            migrationBuilder.Sql(
                $"""
                DO $$
                DECLARE
                    duplicates text;
                BEGIN
                    SELECT string_agg(ids, '; ' ORDER BY ids COLLATE "C") INTO duplicates FROM (
                        SELECT '(' || string_agg(id::text, ', ' ORDER BY id) || ')' AS ids
                        FROM projects GROUP BY lower(name) HAVING count(*) > 1
                    ) shared;
                    IF duplicates IS NOT NULL THEN
                        RAISE EXCEPTION '{DuplicateNamesMessage}%', duplicates;
                    END IF;
                END
                $$;
                """);

            migrationBuilder.DropIndex(
                name: "IX_projects_name",
                table: "projects");

            migrationBuilder.AddColumn<string>(
                name: "name_normalized",
                table: "projects",
                type: "text",
                nullable: false,
                computedColumnSql: "lower(name)",
                stored: true);

            migrationBuilder.CreateIndex(
                name: "IX_projects_name_normalized",
                table: "projects",
                column: "name_normalized",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_projects_name_normalized",
                table: "projects");

            migrationBuilder.DropColumn(
                name: "name_normalized",
                table: "projects");

            migrationBuilder.CreateIndex(
                name: "IX_projects_name",
                table: "projects",
                column: "name",
                unique: true);
        }
    }
}
