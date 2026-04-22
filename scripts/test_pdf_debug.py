import asyncio
import io

import httpx
import pdfplumber


async def test():
    url = "https://www.irs.gov/pub/irs-pdf/f1040.pdf"
    print(f"Downloading: {url}")
    async with httpx.AsyncClient(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "RegulatoryWatch/1.0"},
    ) as client:
        resp = await client.get(url)
        print(
            f"Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type')}, "
            f"Size: {len(resp.content)} bytes"
        )
        if resp.status_code == 200:
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                print(f"Pages: {len(pdf.pages)}")
                if pdf.pages:
                    text = pdf.pages[0].extract_text()
                    print(f"Page 1 text preview: {text[:200] if text else 'EMPTY'}")


asyncio.run(test())

