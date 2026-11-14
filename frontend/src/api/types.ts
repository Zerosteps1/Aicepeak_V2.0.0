/** The signed-in user's record, keyed by Microsoft Entra tenant ID (`tid`) and object ID (`oid`). */
export type User = {
  tid: string
  oid: string
  name: string
}
