import re
import requests
from yt_dlp import YoutubeDL

INPUT_JS_FILE = "script_cleaned.js"
INPUT_LINKS_FILE = "links.txt"
OUTPUT_FILE = "script_cleaned.js"

FALLBACK_THUMBNAIL = "images/no-thumbnail.jpg"
THUMBNAIL_TIMEOUT = 8
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def print_section(title):
    print(f"\n{'=' * 12} {title} {'=' * 12}")


def normalize_url(url):
    if not url:
        return ""
    url = url.strip()
    url = url.rstrip(".,;)")
    url = url.rstrip("/")
    return url


def extract_urls(text):
    raw_urls = re.findall(r'https?://[^\s"\']+', text)
    cleaned = []
    seen = set()

    for url in raw_urls:
        normalized = normalize_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            cleaned.append(normalized)

    return cleaned


def clean_text(text):
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
            .replace('"', "'")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " ")
            .strip()
    )


def truncate_text(text, max_length=150):
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def get_ydl():
    return YoutubeDL({
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 12
    })


def is_video_available(url):
    try:
        with get_ydl() as ydl:
            ydl.extract_info(url, download=False)
        return True
    except Exception:
        return False


def is_thumbnail_ok(url):
    if not url or url == FALLBACK_THUMBNAIL:
        return False

    try:
        response = requests.get(
            url,
            timeout=THUMBNAIL_TIMEOUT,
            headers=REQUEST_HEADERS,
            allow_redirects=True
        )
        content_type = response.headers.get("Content-Type", "").lower()
        return response.status_code == 200 and "image" in content_type
    except Exception:
        return False


def get_video_info(url):
    try:
        with get_ydl() as ydl:
            info = ydl.extract_info(url, download=False)

        title = clean_text(info.get("title", "Ohne Titel"))
        description = clean_text(info.get("description", ""))

        if not description:
            description = title

        description = truncate_text(description, 150)
        thumbnail = info.get("thumbnail", FALLBACK_THUMBNAIL)

        return {
            "title": title or "Ohne Titel",
            "description": description or "Ohne Beschreibung",
            "thumbnail": thumbnail if thumbnail else FALLBACK_THUMBNAIL
        }

    except Exception as e:
        print(f"Fehler beim Lesen von {url}: {e}")
        return None


def split_objects(array_text):
    objects = []
    depth = 0
    start = None
    in_string = False
    escape = False
    string_char = ""

    for i, ch in enumerate(array_text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(array_text[start:i + 1])
                    start = None

    return objects


def get_existing_array(content):
    match = re.search(
        r'const\s+videos\s*=\s*\[(.*?)\]\s*;',
        content,
        re.DOTALL
    )
    if not match:
        return None, None, None
    return match.group(1), match.start(), match.end()


def get_field(obj, field_name):
    match = re.search(rf'{field_name}\s*:\s*"([^"]*)"', obj)
    return match.group(1).strip() if match else ""


def replace_field(obj, field_name, new_value):
    pattern = rf'({field_name}\s*:\s*")([^"]*)(")'
    if re.search(pattern, obj):
        return re.sub(pattern, rf'\1{new_value}\3', obj)
    return obj


def get_existing_urls(objects):
    urls = set()
    for obj in objects:
        url = normalize_url(get_field(obj, "url"))
        if url:
            urls.add(url)
    return urls


def get_highest_id(objects):
    max_id = 0
    for obj in objects:
        match = re.search(r'id\s*:\s*"custom-(\d+)"', obj)
        if match:
            num = int(match.group(1))
            if num > max_id:
                max_id = num
    return max_id


def detect_channel(url):
    u = url.lower()
    if "pornhub" in u:
        return "Pornhub"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "xvideos" in u:
        return "XVideos"
    if "xhamster" in u:
        return "xHamster"
    if "redtube" in u:
        return "RedTube"
    return "Auto"


def build_video_block(video_id, title, description, thumbnail, url, channel):
    title = clean_text(title)
    description = clean_text(description)
    thumbnail = clean_text(thumbnail)
    url = clean_text(url)
    channel = clean_text(channel)

    return f'''  {{
    id: "custom-{video_id}",
    title: "{title}",
    description: "{description}",
    channel: "{channel}",
    platform: "custom",
    thumbnail: "{thumbnail}",
    url: "{url}"
  }}'''


def process_existing_objects(existing_objects):
    kept_objects = []

    removed_old_videos = 0
    replaced_old_thumbnails = 0
    recovered_real_thumbnails = 0
    unchanged_fallbacks = 0

    print_section("PRÜFE ALTE BOXEN")

    for obj in existing_objects:
        url = normalize_url(get_field(obj, "url"))
        current_thumbnail = get_field(obj, "thumbnail")

        if not url:
            print("Objekt ohne URL -> übersprungen")
            continue

        print(f"Prüfe altes Video: {url}")

        if not is_video_available(url):
            print("VIDEO NICHT VERFÜGBAR -> BOX GELÖSCHT")
            removed_old_videos += 1
            continue

        # Wenn Ersatzbild drin ist -> immer wieder versuchen ein echtes Thumbnail zu holen
        if current_thumbnail == FALLBACK_THUMBNAIL:
            print("Ersatzbild erkannt -> versuche echtes Thumbnail neu zu holen")
            info = get_video_info(url)

            if info:
                new_thumbnail = info.get("thumbnail", FALLBACK_THUMBNAIL)
                if new_thumbnail and new_thumbnail != FALLBACK_THUMBNAIL and is_thumbnail_ok(new_thumbnail):
                    obj = replace_field(obj, "thumbnail", new_thumbnail)
                    recovered_real_thumbnails += 1
                    print("ECHTES THUMBNAIL ERFOLGREICH GESETZT")
                else:
                    unchanged_fallbacks += 1
                    print("Kein echtes Thumbnail gefunden -> Ersatzbild bleibt")
            else:
                unchanged_fallbacks += 1
                print("Video-Infos konnten nicht geladen werden -> Ersatzbild bleibt")

        elif current_thumbnail:
            if not is_thumbnail_ok(current_thumbnail):
                obj = replace_field(obj, "thumbnail", FALLBACK_THUMBNAIL)
                replaced_old_thumbnails += 1
                print("Altes Thumbnail kaputt -> Ersatzbild gesetzt")
            else:
                print("Altes Thumbnail OK")
        else:
            obj = replace_field(obj, "thumbnail", FALLBACK_THUMBNAIL)
            replaced_old_thumbnails += 1
            print("Thumbnail leer -> Ersatzbild gesetzt")

        kept_objects.append(obj)

    return {
        "objects": kept_objects,
        "removed_old_videos": removed_old_videos,
        "replaced_old_thumbnails": replaced_old_thumbnails,
        "recovered_real_thumbnails": recovered_real_thumbnails,
        "unchanged_fallbacks": unchanged_fallbacks
    }


def process_new_links(existing_objects, existing_urls):
    current_max_id = get_highest_id(existing_objects)

    print_section("LESE NEUE LINKS AUS links.txt")

    try:
        with open(INPUT_LINKS_FILE, "r", encoding="utf-8") as f:
            links_text = f.read()
    except FileNotFoundError:
        links_text = ""

    new_urls = extract_urls(links_text)

    added_count = 0
    duplicate_count = 0
    invalid_count = 0
    replaced_new_thumbnails = 0

    if not new_urls:
        print("Keine neuen Links gefunden.")

    for url in new_urls:
        if url in existing_urls:
            print(f"Schon vorhanden -> übersprungen: {url}")
            duplicate_count += 1
            continue

        print(f"Prüfe neuen Link: {url}")

        if not is_video_available(url):
            print("NEUES VIDEO NICHT VERFÜGBAR -> übersprungen")
            invalid_count += 1
            continue

        info = get_video_info(url)
        if not info:
            print("Infos konnten nicht geladen werden -> übersprungen")
            invalid_count += 1
            continue

        thumbnail = info["thumbnail"]
        if not thumbnail or not is_thumbnail_ok(thumbnail):
            thumbnail = FALLBACK_THUMBNAIL
            replaced_new_thumbnails += 1
            print("Neues Thumbnail kaputt/fehlt -> Ersatzbild gesetzt")
        else:
            print("Echtes Thumbnail gefunden")

        current_max_id += 1
        channel = detect_channel(url)

        new_object = build_video_block(
            video_id=current_max_id,
            title=info["title"],
            description=info["description"],
            thumbnail=thumbnail,
            url=url,
            channel=channel
        )

        existing_objects.append(new_object)
        existing_urls.add(url)
        added_count += 1
        print("NEUE BOX HINZUGEFÜGT")

    return {
        "objects": existing_objects,
        "added_count": added_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "replaced_new_thumbnails": replaced_new_thumbnails
    }


def clear_links_file():
    try:
        with open(INPUT_LINKS_FILE, "w", encoding="utf-8") as f:
            f.write("")
        print("links.txt wurde geleert.")
    except Exception as e:
        print(f"links.txt konnte nicht geleert werden: {e}")


def main():
    try:
        with open(INPUT_JS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"FEHLER: {INPUT_JS_FILE} nicht gefunden.")
        return

    array_inner, start, end = get_existing_array(content)

    if array_inner is None:
        print("FEHLER: videos-Array nicht gefunden.")
        return

    existing_objects = split_objects(array_inner)

    old_result = process_existing_objects(existing_objects)
    existing_objects = old_result["objects"]

    existing_urls = get_existing_urls(existing_objects)

    new_result = process_new_links(existing_objects, existing_urls)
    existing_objects = new_result["objects"]

    new_array = "const videos = [\n" + ",\n".join(existing_objects) + "\n];"
    new_content = content[:start] + new_array + content[end:]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    clear_links_file()

    print_section("FERTIG")
    print(f"Alte Boxen gelöscht: {old_result['removed_old_videos']}")
    print(f"Alte kaputte Thumbnails ersetzt: {old_result['replaced_old_thumbnails']}")
    print(f"Echte Thumbnails nachträglich geholt: {old_result['recovered_real_thumbnails']}")
    print(f"Ersatzbilder beibehalten: {old_result['unchanged_fallbacks']}")
    print(f"Neue Boxen hinzugefügt: {new_result['added_count']}")
    print(f"Doppelte neue Links übersprungen: {new_result['duplicate_count']}")
    print(f"Ungültige neue Links übersprungen: {new_result['invalid_count']}")
    print(f"Neue Ersatzbilder gesetzt: {new_result['replaced_new_thumbnails']}")
    print(f"Gesamt verbleibende Boxen: {len(existing_objects)}")


if __name__ == "__main__":
    main()