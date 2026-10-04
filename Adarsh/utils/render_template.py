from Adarsh.vars import Var
from Adarsh.bot import StreamBot
from Adarsh.utils.human_readable import humanbytes
from Adarsh.utils.file_properties import get_file_ids, hash_ok
from Adarsh.utils.access import access_db
from Adarsh.utils.link_expiry import link_expiry
from Adarsh.server.exceptions import InvalidHash, FIleNotFound, LinkExpired
import html
import urllib.parse
import aiofiles
import logging
logger = logging.getLogger("Adarsh.utils.render_template")


async def render_page(id, secure_hash):
    if await access_db.is_revoked(id):
        raise FIleNotFound
    file_data = await get_file_ids(StreamBot, int(Var.BIN_CHANNEL), int(id))
    if not hash_ok(file_data.unique_id, secure_hash):
        logger.debug(f"Invalid hash for message with - ID {id}")
        raise InvalidHash
    if await link_expiry.is_expired(id):
        raise LinkExpired
    src = html.escape(urllib.parse.urljoin(Var.URL, f'{int(id)}/?hash={urllib.parse.quote(secure_hash)}'), quote=True)
    # File names are chosen by whoever uploaded the file: always escape before putting them in HTML.
    name = html.escape(file_data.file_name or "file")
    kind = (file_data.mime_type or "").split('/')[0].strip()
    if kind in ('video', 'audio'):
        heading = '{} {}'.format('Watch' if kind == 'video' else 'Listen', name)
        async with aiofiles.open('Adarsh/template/req.html') as r:
            page = (await r.read()).replace('__MEDIA__', kind) % (heading, name, src)
    else:
        heading = 'Download {}'.format(name)
        async with aiofiles.open('Adarsh/template/dl.html') as r:
            page = (await r.read()) % (heading, name, src, humanbytes(int(file_data.file_size or 0)))
    return page
