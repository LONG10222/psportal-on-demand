// SPDX-License-Identifier: GPL-3.0-only
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
/// A small Objective-C boundary keeps gomobile's NSError ABI out of Swift UI code.
@interface PSPortalEngineBridge : NSObject
+ (nullable NSString *)startWithConfigJSON:(NSString *)configJSON NS_SWIFT_NAME(start(configJSON:));
+ (void)stop NS_SWIFT_NAME(stop());
+ (NSString *)statusJSON NS_SWIFT_NAME(statusJSON());
@end
NS_ASSUME_NONNULL_END

