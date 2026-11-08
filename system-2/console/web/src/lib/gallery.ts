// The sim devices' gallery entries (each device's gallery.md, through docs/devices.md and wiki-docs.json), for the
// wiki and the project screens. Held-out devices arrive with their fault lines already cut, and deviceCards cuts again.
import { deviceCards, type DeviceCard } from "./wikidata";

const data = import.meta.glob("../data/wiki-docs.json", { import: "default", eager: true }) as Record<string, { devices?: string | null } | undefined>;

export const GALLERY: DeviceCard[] = deviceCards(data["../data/wiki-docs.json"]?.devices);

export const galleryOf = (projectId: string | undefined): DeviceCard | undefined => GALLERY.find((c) => c.project === projectId || c.id === projectId);

export const SPLIT_LABEL: Record<string, string> = { dev: "Dev", validation: "Validation", held_out: "Held out", "held-out": "Held out" };
export const splitLabel = (split: string | null | undefined) => (split ? SPLIT_LABEL[split] ?? split : null);
