import { Module } from '@nestjs/common';

import { AuditService } from './common/audit.service';
import { CryptoService } from './common/crypto.service';
import { DbService } from './db/db.service';
import { AuthController } from './modules/auth/auth.controller';
import { ClientsController } from './modules/clients/clients.controller';
import { ClientsService } from './modules/clients/clients.service';
import { IngestionController } from './modules/ingestion/ingestion.controller';
import { IngestionService } from './modules/ingestion/ingestion.service';
import { ParserClient } from './modules/ingestion/parser.client';
import { PortfolioService } from './modules/portfolio/portfolio.service';

/**
 * Modular Monolith.
 *
 * הגבולות בין המודולים נשמרים בקוד (כל מודול חושף Service ולא Repository),
 * כדי שהפיצול לשירותים נפרדים — כשהעומס יצדיק אותו — יהיה חילוץ ולא
 * כתיבה מחדש. ראה 01-architecture.md §2.
 */
@Module({
  controllers: [AuthController, ClientsController, IngestionController],
  providers: [
    DbService,
    CryptoService,
    AuditService,
    ClientsService,
    PortfolioService,
    IngestionService,
    ParserClient,
  ],
})
export class AppModule {}
