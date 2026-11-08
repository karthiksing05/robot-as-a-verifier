// Each project's picture, rendered from its CAD (or the sim scene) into subjects/<id>/preview.jpg.
const FILES = import.meta.glob("@repo/subjects/*/preview.jpg", { eager: true, query: "?url", import: "default" }) as Record<string, string>;

const BY_ID = new Map(Object.entries(FILES).map(([path, url]) => [path.split("/").at(-2) ?? "", url]));

export const previewOf = (id: string | null | undefined): string | undefined => (id ? BY_ID.get(id) : undefined);
