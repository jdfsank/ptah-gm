#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef STUDIO_GODOT_CA_BUNDLE_PATH
#error "The trusted CA bundle path must be bound at compile time."
#endif

#define DYLD_INTERPOSE(replacement, replacee) \
    __attribute__((used)) static struct { \
        const void *replacement; \
        const void *replacee; \
    } _studio_interpose_##replacee \
        __attribute__((section("__DATA,__interpose"))) = { \
            (const void *)(unsigned long)&replacement, \
            (const void *)(unsigned long)&replacee \
        }

#define STUDIO_CA_BUNDLE_MAX_BYTES (16 * 1024 * 1024)

static pthread_once_t g_once = PTHREAD_ONCE_INIT;
static CFArrayRef g_anchors = NULL;
static OSStatus g_initialization_status = errSecInternalComponent;

static bool studio_whitespace_only(NSString *text, NSRange range) {
    NSCharacterSet *whitespace = [NSCharacterSet whitespaceAndNewlineCharacterSet];
    for (NSUInteger index = range.location; index < NSMaxRange(range); index++) {
        if (![whitespace characterIsMember:[text characterAtIndex:index]]) {
            return false;
        }
    }
    return true;
}

static bool studio_valid_base64(NSString *text) {
    if (text.length == 0 || text.length % 4 != 0) {
        return false;
    }
    BOOL saw_padding = NO;
    for (NSUInteger index = 0; index < text.length; index++) {
        unichar character = [text characterAtIndex:index];
        BOOL base64_character = (character >= 'A' && character <= 'Z')
            || (character >= 'a' && character <= 'z')
            || (character >= '0' && character <= '9')
            || character == '+' || character == '/';
        if (character == '=') {
            saw_padding = YES;
            if (index + 2 < text.length) {
                return false;
            }
        } else if (!base64_character || saw_padding) {
            return false;
        }
    }
    return true;
}

static CFArrayRef studio_parse_certificates(NSString *pem) {
    NSString *begin_marker = @"-----BEGIN CERTIFICATE-----";
    NSString *end_marker = @"-----END CERTIFICATE-----";
    NSMutableArray *certificates = [NSMutableArray array];
    NSUInteger cursor = 0;

    while (cursor < pem.length) {
        NSRange begin = [pem rangeOfString:begin_marker
                                   options:0
                                     range:NSMakeRange(cursor, pem.length - cursor)];
        if (begin.location == NSNotFound) {
            return studio_whitespace_only(pem, NSMakeRange(cursor, pem.length - cursor))
                ? CFBridgingRetain(certificates) : NULL;
        }
        if (!studio_whitespace_only(pem, NSMakeRange(cursor, begin.location - cursor))) {
            return NULL;
        }

        NSUInteger body_start = NSMaxRange(begin);
        NSRange end = [pem rangeOfString:end_marker
                                 options:0
                                   range:NSMakeRange(body_start, pem.length - body_start)];
        if (end.location == NSNotFound) {
            return NULL;
        }
        NSRange nested_begin = [pem rangeOfString:begin_marker
                                          options:0
                                            range:NSMakeRange(body_start, end.location - body_start)];
        if (nested_begin.location != NSNotFound) {
            return NULL;
        }

        NSString *body = [pem substringWithRange:NSMakeRange(body_start, end.location - body_start)];
        NSMutableString *compact = [NSMutableString stringWithCapacity:body.length];
        NSCharacterSet *whitespace = [NSCharacterSet whitespaceAndNewlineCharacterSet];
        for (NSUInteger index = 0; index < body.length; index++) {
            unichar character = [body characterAtIndex:index];
            if ([whitespace characterIsMember:character]) {
                continue;
            }
            [compact appendFormat:@"%C", character];
        }
        if (!studio_valid_base64(compact)) {
            return NULL;
        }
        NSData *der = [[NSData alloc] initWithBase64EncodedString:compact options:0];
        if (der == nil || der.length == 0) {
            return NULL;
        }
        SecCertificateRef certificate = SecCertificateCreateWithData(
            kCFAllocatorDefault, (__bridge CFDataRef)der);
        if (certificate == NULL) {
            return NULL;
        }
        [certificates addObject:(__bridge id)certificate];
        CFRelease(certificate);
        cursor = NSMaxRange(end);
    }

    if (certificates.count == 0) {
        return NULL;
    }
    return CFBridgingRetain(certificates);
}

static void studio_initialize(void) {
    @autoreleasepool {
        const char *path = STUDIO_GODOT_CA_BUNDLE_PATH;
        int descriptor = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        if (descriptor < 0) {
            g_initialization_status = (errno == EACCES || errno == EPERM)
                ? errSecAuthFailed : errSecIO;
            return;
        }

        struct stat before = {0};
        struct stat after = {0};
        if (fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode)
                || before.st_size <= 0 || before.st_size > STUDIO_CA_BUNDLE_MAX_BYTES) {
            close(descriptor);
            g_initialization_status = errSecDecode;
            return;
        }

        NSMutableData *contents = [NSMutableData dataWithCapacity:(NSUInteger)before.st_size];
        unsigned char buffer[65536];
        bool read_failed = false;
        for (;;) {
            ssize_t count = read(descriptor, buffer, sizeof(buffer));
            if (count == 0) {
                break;
            }
            if (count < 0) {
                if (errno == EINTR) {
                    continue;
                }
                read_failed = true;
                break;
            }
            [contents appendBytes:buffer length:(NSUInteger)count];
            if (contents.length > STUDIO_CA_BUNDLE_MAX_BYTES) {
                read_failed = true;
                break;
            }
        }
        bool metadata_read = fstat(descriptor, &after) == 0;
        close(descriptor);
        if (read_failed || !metadata_read || contents.length != (NSUInteger)before.st_size
                || before.st_dev != after.st_dev || before.st_ino != after.st_ino
                || before.st_size != after.st_size || before.st_mtime != after.st_mtime
                || before.st_ctime != after.st_ctime) {
            g_initialization_status = errSecDecode;
            return;
        }

        NSString *pem = [[NSString alloc] initWithData:contents encoding:NSASCIIStringEncoding];
        if (pem == nil) {
            g_initialization_status = errSecDecode;
            return;
        }
        g_anchors = studio_parse_certificates(pem);
        if (g_anchors == NULL || CFArrayGetCount(g_anchors) == 0) {
            if (g_anchors != NULL) {
                CFRelease(g_anchors);
                g_anchors = NULL;
            }
            g_initialization_status = errSecDecode;
            return;
        }
        g_initialization_status = errSecSuccess;
    }
}

static OSStatus studio_SecTrustCopyAnchorCertificates(CFArrayRef *anchors) {
    if (anchors == NULL) {
        return errSecParam;
    }
    *anchors = NULL;
    pthread_once(&g_once, studio_initialize);
    if (g_initialization_status != errSecSuccess || g_anchors == NULL
            || CFArrayGetCount(g_anchors) == 0) {
        return g_initialization_status == errSecSuccess
            ? errSecInternalComponent : g_initialization_status;
    }
    *anchors = (CFArrayRef)CFRetain(g_anchors);
    return errSecSuccess;
}

DYLD_INTERPOSE(studio_SecTrustCopyAnchorCertificates, SecTrustCopyAnchorCertificates);
