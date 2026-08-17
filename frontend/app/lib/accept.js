"use client";

// What the file inputs will offer — and, mostly, the decision not to filter.
//
// The history here matters, because this has been "fixed" twice and stayed
// broken both times. First the inputs listed bare extensions (".txt,.zip"),
// and Android's picker, which filters on MIME type, matched nothing and fell
// back to showing images alone — so the screen looked like a photo picker.
// Then MIME types were added alongside the extensions, which is correct and
// still not enough: Android hands files out of Downloads and the share sheet
// with whatever type the writing app declared, and a WhatsApp export very
// often arrives as application/octet-stream or with no type at all. Any filter
// greys those out. On a phone the owner sees their export in the list, cannot
// tap it, and concludes the app is broken. They are not wrong.
//
// So on anything the owner picks from their own storage there is no filter.
// The importer validates every file server-side and the estimate reports what
// it could not read, per file, before anything is committed — which is a far
// better place to catch a wrong pick than a picker that silently refuses to
// offer the right one. The hint text next to each input says what to choose.
//
// The one exception is the camera, where accept="image/*" together with
// capture is what makes the phone open the camera instead of the file list.
// That is the attribute doing a job, not a filter.
//
// If you are about to add an accept list to a file input on this screen:
// don't. Add the format to SUPPORTED in app/services/intake.py instead, so
// the file is actually read.

// Deliberately undefined. Passing `accept={ANY_FILE}` reads as a decision,
// where an absent attribute reads as an oversight and gets "fixed".
export const ANY_FILE = undefined;

// Camera capture only.
export const IMAGE_ACCEPT = "image/*";
