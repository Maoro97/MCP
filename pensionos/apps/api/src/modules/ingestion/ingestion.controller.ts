import {
  BadRequestException,
  Controller,
  Get,
  Param,
  ParseUUIDPipe,
  Post,
  UploadedFile,
  UseGuards,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';

import { AuthGuard } from '../../common/auth.guard';
import { CurrentUser, type Principal } from '../../common/principal';
import { IngestionService, type IngestSummary } from './ingestion.service';
import { ParserClient } from './parser.client';

const MAX_UPLOAD = Number(process.env.MAX_UPLOAD_BYTES ?? 200 * 1024 * 1024);

@Controller('v1')
export class IngestionController {
  constructor(
    private readonly ingestion: IngestionService,
    private readonly parser: ParserClient,
  ) {}

  /** בריאות מנוע הפענוח — נבדק גם ע"י ה-UI לפני שמציע העלאה. */
  @Get('ingestion/health')
  async health() {
    return { parser: (await this.parser.health()) ? 'up' : 'down' };
  }

  @Post('clients/:id/ingest')
  @UseGuards(AuthGuard)
  @UseInterceptors(FileInterceptor('file', { limits: { fileSize: MAX_UPLOAD } }))
  async ingest(
    @CurrentUser() principal: Principal,
    @Param('id', ParseUUIDPipe) clientId: string,
    @UploadedFile() file?: Express.Multer.File,
  ): Promise<IngestSummary> {
    if (!file?.buffer?.length) {
      throw new BadRequestException('לא צורף קובץ');
    }
    return this.ingestion.ingest(principal, clientId, {
      buffer: file.buffer,
      originalname: file.originalname,
    });
  }
}
