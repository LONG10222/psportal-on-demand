// SPDX-License-Identifier: GPL-3.0-only
#import "PSPortalEngineBridge.h"
// This is the actual gomobile static XCFramework, never a fallback stub.
#import <PSPortalEngine/PSPortalEngine.h>

@implementation PSPortalEngineBridge
+ (nullable NSString *)startWithConfigJSON:(NSString *)configJSON {
    NSError *error = nil;
    if (!MobileStart(configJSON, &error)) {
        // Do not display or log arbitrary native errors or the input JSON.
        return @"The proxy could not start. Check the Wi-Fi address, port, and configuration.";
    }
    return nil;
}
+ (void)stop { MobileStop(); }
+ (NSString *)statusJSON { return MobileStatus(); }
+ (NSString *)subscriptionInfo:(NSString *)url { return MobileSubscriptionInfo(url); }
@end

