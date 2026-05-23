import asyncio
import sys
import traceback
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from playwright.async_api import async_playwright
from openai import AsyncOpenAI

# Import project settings
# Ensure project root is in path
import os
sys.path.append(os.getcwd())

from src.core.config import settings

console = Console()

def mask_secret(secret: Optional[str]) -> str:
    if not secret:
        return "MISSING"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"

async def check_config():
    console.print("[bold blue]1. Config Check[/bold blue]")
    try:
        env = settings.ENV.upper()
        debug = settings.DEBUG
        db_url = settings.DATABASE_URL
        openai_key = settings.OPENAI_API_KEY
        
        console.print(f"  Environment: [bold]{env}[/bold]")
        console.print(f"  Debug Mode: [bold]{debug}[/bold]")
        console.print(f"  Database URL: [yellow]{mask_secret(db_url)}[/yellow]")
        console.print(f"  OpenAI API Key: [yellow]{mask_secret(openai_key)}[/yellow]")
        
        if not openai_key:
            console.print("  [yellow]Warning: OPENAI_API_KEY is not set.[/yellow]")
            
        return True
    except Exception as e:
        console.print(f"  [red]❌ Config Check Failed:[/red] {e}")
        return False

async def check_database():
    console.print("\n[bold blue]2. Database Connectivity (Async)[/bold blue]")
    engine = None
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version();"))
            version = result.scalar()
            console.print(f"  [green]✅ Connected to PostgreSQL[/green]")
            console.print(f"  [dim]DB Version: {version}[/dim]")
            return True
    except Exception as e:
        console.print(f"  [red]❌ Database Connection Failed:[/red] {e}")
        # traceback.print_exc()
        return False
    finally:
        if engine:
            await engine.dispose()

async def check_migrations():
    console.print("\n[bold blue]3. ORM & Migrations Check[/bold blue]")
    engine = None
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.connect() as conn:
            # Check if alembic_version table exists
            query = text("SELECT table_name FROM information_schema.tables WHERE table_name = 'alembic_version';")
            result = await conn.execute(query)
            row = result.fetchone()
            if row:
                console.print("  [green]✅ alembic_version table found (Migrations initialized)[/green]")
            else:
                console.print("  [yellow]⚠️ alembic_version table NOT found (Migrations might not be applied)[/yellow]")
            return True
    except Exception as e:
        console.print(f"  [red]❌ Migrations Check Failed:[/red] {e}")
        return False
    finally:
        if engine:
            await engine.dispose()

async def check_playwright():
    console.print("\n[bold blue]4. Playwright Check[/bold blue]")
    try:
        async with async_playwright() as p:
            console.print("  Launching Browser...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("http://example.com")
            title = await page.title()
            console.print(f"  [green]✅ Playwright Engine OK[/green]")
            console.print(f"  [dim]Example Page Title: {title}[/dim]")
            await browser.close()
            return True
    except Exception as e:
        console.print(f"  [red]❌ Playwright Check Failed:[/red] {e}")
        # console.print(f"  [dim]Tip: Try 'playwright install chromium' if browser is missing.[/dim]")
        return False

async def check_openai():
    console.print("\n[bold blue]5. OpenAI Client Check[/bold blue]")
    try:
        if not settings.OPENAI_API_KEY:
             console.print("  [yellow]⚠️ OpenAI API Key missing, skipping client init check[/yellow]")
             return True
             
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        console.print(f"  [green]✅ AsyncOpenAI client initialized[/green]")
        console.print(f"  [dim]API Key present: {mask_secret(settings.OPENAI_API_KEY)}[/dim]")
        return True
    except Exception as e:
        console.print(f"  [red]❌ OpenAI Client Check Failed:[/red] {e}")
        return False

async def main():
    console.print(Panel.fit(
        "[bold cyan]Google Maps Scraper Infrastructure Healthcheck[/bold cyan]",
        border_style="cyan"
    ))
    
    results = {}
    results["Config"] = await check_config()
    results["Database"] = await check_database()
    results["Migrations"] = await check_migrations()
    results["Playwright"] = await check_playwright()
    results["OpenAI"] = await check_openai()
    
    console.print("\n" + "="*40)
    table = Table(title="Summary Results")
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")
    
    for component, passed in results.items():
        status = "[green]PASS[/green] ✅" if passed else "[red]FAIL[/red] ❌"
        table.add_row(component, status)
        
    console.print(table)
    
    if all(results.values()):
        console.print("\n[bold green]Success: All core systems are ready for production![/bold green]")
    else:
        console.print("\n[bold red]Warning: Some components failed the healthcheck. Please review logs above.[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    # Instructions to run: 
    # poetry run python scripts/healthcheck.py
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Healthcheck interrupted by user.[/yellow]")
        sys.exit(0)
