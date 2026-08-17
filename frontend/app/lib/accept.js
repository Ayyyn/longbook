"use client";

// What the file inputs will offer, in one place.
//
// Both MIME types and extensions are listed on purpose. Android's picker
// filters on MIME and matches nothing for a bare ".xlsx" or ".txt"; desktop
// browsers match extensions more reliably. Give it only extensions and Android
// quietly falls back to images alone — or to nothing selectable at all, which
// looks exactly like a broken app and is the reason this file exists: the Add
// data screen was fixed and the signup screen was not, so setup went on
// refusing to accept a chat export for weeks after the bug was "fixed".
//
// Keep in step with SUPPORTED in app/services/intake.py. Anything offered here
// and not handled there is a file the owner picks and then gets a 415 for.

const TEXT = ".txt,text/plain";
// Android hands files out of Downloads and the share sheet with a generic
// type more often than it should — a WhatsApp export arriving as
// application/octet-stream is common. Listing it means the picker shows the
// file rather than greying it out; a wrong pick is caught server-side and
// reported per file, which is a far better failure than not being able to
// choose anything.
const ZIP = ".zip,application/zip,application/x-zip-compressed,application/octet-stream";
const SHEET =
  ".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet," +
  "application/vnd.ms-excel";
const CSV = ".csv,text/csv";
const PDF = ".pdf,application/pdf";
const IMAGE = ".jpg,.jpeg,.png,.webp,.heic,.heif,image/*";
const AUDIO = ".ogg,.oga,.opus,.m4a,.mp3,.wav,.aac,.webm,audio/*";

// Everything the importer handles.
export const DEVICE_ACCEPT = [TEXT, ZIP, PDF, CSV, SHEET, IMAGE, AUDIO].join(",");

// A WhatsApp export: .txt without media, .zip with it.
export const CHAT_ACCEPT = [TEXT, ZIP].join(",");

// A customer list. Matches parse_upload() in app/services/party_import.py
// exactly — that function takes a Tally XML master export or an .xlsx/.xlsm
// workbook, and nothing else.
//
// The XML is here because it was missing: the label offered "Tally or Excel"
// while the picker accepted only spreadsheets, so the one format the importer
// handles best could not be selected. CSV is deliberately absent — the parser
// rejects it, and offering a file that is refused after upload is worse than
// not offering it.
export const PARTY_ACCEPT = [".xml,text/xml,application/xml", SHEET].join(",");

export const IMAGE_ACCEPT = IMAGE;
