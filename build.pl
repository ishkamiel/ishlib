#! /usr/bin/env perl

use warnings;
use strict;

use Carp;
use File::Basename;
use File::Spec;

my $ishlib_name    = "ishlib";
my $ishlib_version = '';

my $base_fn   = 'src/base.sh';
my $output_fn = 'ishlib.sh';

my $header_end =
'###############################################################################';

# my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');

my $src_dir = dirname($base_fn);

my $current_fn = $base_fn;
my $empty_lines = 0;

sub set_version {
    my ( $sec, $min, $hour, $mday, $mon, $year, $wday, $yday, $isdst ) =
      localtime();
    my $git_revision = `git rev-parse --short HEAD`;
    chomp $git_revision;

    $ishlib_version = sprintf(
        "%04d-%02d-%02d.%02d%02d.%s",
        $year + 1900,
        $mon + 1, $mday, $hour, $min, $git_revision
    );
    return;
}

sub source_file {
    my ( $out_fh, $fn_base ) = @_;

    my $start_reading = 0;
    my $fn            = File::Spec->catfile( $src_dir, $fn_base );

    print "Sourcing $fn\n";

    # Update $current_fn
    my $old_fn = $current_fn;
    $current_fn = $fn;

    open my $fh, "<", "$fn" or croak "Failed to open < $fn";
    while (<$fh>) {
        if (m/^$header_end\s*$/) {
            $start_reading = 1;
        } elsif ($start_reading) {
            process_oneline( $out_fh, $_ );
        }
    }
    close $fh;

    # Restore $current_fn
    $current_fn = $old_fn;
    return;
}

sub process_oneline {
    my ( $out_fh, $line ) = @_;

    # chomp $line;
    $line =~ s/__ISHLIB_VERSION__/$ishlib_version/g;
    $line =~ s/__ISHLIB_NAME__/$ishlib_name/g;

    if ($line =~ m/^\s*$/) {
        # Squash multiple empty lines
        if ($empty_lines++) {
            print "Squasing repeated empty line in $current_fn\n"
        } else {
            print $out_fh "\n";
        }
    } elsif ( $line =~ m/^\. ([\w_\.]+)$/ ) {
        # Inline source statements
        source_file( $out_fh, $1 );
    } else {
        # Print the line
        $empty_lines = 0;
        print $out_fh $line;
    }

    return;
}

sub build_ishlib {
    set_version();

    print "Starting from base  $base_fn\n";

    open my $base_fh, "<", $base_fn   or croak "Failed to open < $base_fn";
    open my $out_fh,  ">", $output_fn or croak "Cannot open > $output_fn";

    while (<$base_fh>) {
        process_oneline( $out_fh, $_ );
    }

    close $base_fh;
    close $out_fh;
    return;
}

build_ishlib();

1;
