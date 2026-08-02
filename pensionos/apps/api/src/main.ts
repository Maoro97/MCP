import 'reflect-metadata';

import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { ZodError } from 'zod';

import { AppModule } from './app.module';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, {
    logger: ['error', 'warn', 'log'],
  });

  // אין ValidationPipe: הוולידציה כולה ב-Zod, שהוא מקור האמת היחיד
  // לטיפוסים ומשותף עם ה-Frontend. שתי מערכות ולידציה = שתי אמיתות.
  // שגיאות Zod מתורגמות ל-422 עם רשימת השדות הבעייתיים, כדי שה-UI יוכל
  // להצביע על השדה ולא רק להציג "שגיאה".
  app.useGlobalFilters({
    catch(exception: unknown, host: any) {
      const res = host.switchToHttp().getResponse();
      if (exception instanceof ZodError) {
        return res.status(422).json({
          statusCode: 422,
          message: 'שדות לא תקינים',
          issues: exception.issues.map((i) => ({
            field: i.path.join('.'),
            message: i.message,
          })),
        });
      }
      const status = (exception as any)?.status ?? 500;
      const body = (exception as any)?.response ?? {
        statusCode: status,
        message: status === 500 ? 'שגיאת שרת' : String((exception as any)?.message ?? ''),
      };
      if (status >= 500) {
        new Logger('ExceptionFilter').error(exception);
      }
      return res.status(status).json(body);
    },
  });

  app.enableCors({
    origin: process.env.CORS_ORIGIN?.split(',') ?? false,
    credentials: true,
  });

  const port = Number(process.env.PORT ?? 8080);
  await app.listen(port, '0.0.0.0');
  new Logger('bootstrap').log(`PensionOS API listening on :${port}`);
}

void bootstrap();
