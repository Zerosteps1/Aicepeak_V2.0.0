using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Aicepeak.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddEntraLogin : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Users are now keyed by tenant ID and object ID. Existing rows only have the old EntraId and cannot be
            // mapped, so the table is recreated; they are created again on the next sign-in.
            migrationBuilder.DropTable(
                name: "Users");

            migrationBuilder.CreateTable(
                name: "Users",
                columns: table => new
                {
                    Tid = table.Column<Guid>(type: "uuid", nullable: false),
                    Oid = table.Column<Guid>(type: "uuid", nullable: false),
                    Name = table.Column<string>(type: "text", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Users", x => new { x.Tid, x.Oid });
                });

            migrationBuilder.CreateTable(
                name: "allowed_tenants",
                columns: table => new
                {
                    tid = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_allowed_tenants", x => x.tid);
                });

            migrationBuilder.InsertData(
                table: "allowed_tenants",
                column: "tid",
                value: new Guid("db760528-cb7c-455c-bd41-e50a38f6fd62"));
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "allowed_tenants");

            migrationBuilder.DropTable(
                name: "Users");

            migrationBuilder.CreateTable(
                name: "Users",
                columns: table => new
                {
                    EntraId = table.Column<string>(type: "text", nullable: false),
                    Name = table.Column<string>(type: "text", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Users", x => x.EntraId);
                });
        }
    }
}
