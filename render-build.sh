#!/usr/bin/env bash
set -o errexit

# Install Python dependencies
pip install -e .

# Build frontend
cd frontend
npm install
npm run build
cd ..

# Run database migrations
alembic upgrade head

# Seed domains if needed
python -c "
import asyncio
from app.database import get_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

async def seed():
    engine = get_engine()
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text('SELECT COUNT(*) FROM domains'))
        count = result.scalar()
        if count == 0:
            domains = [
                ('Front-End Design', 'front-end-design', 0),
                ('DFT', 'dft', 1),
                ('Verification', 'verification', 2),
                ('Physical Design', 'physical-design', 3),
                ('Si-Ops', 'si-ops', 4),
                ('Architecture', 'architecture', 5),
            ]
            for name, slug, order in domains:
                await session.execute(
                    text('INSERT INTO domains (name, slug, sort_order) VALUES (:n, :s, :o)'),
                    {'n': name, 's': slug, 'o': order}
                )
            await session.commit()
            print(f'Seeded {len(domains)} domains')
        else:
            print(f'Domains already seeded ({count} found)')
    await engine.dispose()

asyncio.run(seed())
" 2>/dev/null || echo "Domain seeding skipped (table may not exist yet)"
